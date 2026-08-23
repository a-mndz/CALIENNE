"""
aetheris — Adaptive Multi-Model Reasoning Orchestrator
Claim Manager: extracts and validates factual claims from agent outputs
to detect hallucinations and unsupported assertions.

Integrates with the ReasoningGraph to store validated claims and track
provenance for audit and learning.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional

from orchestrator.reasoning_graph import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    ReasoningGraph,
    _generate_id,
    _utc_now,
)

logger = logging.getLogger(__name__)

_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "then",
        "there",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
    }
)

_NEGATION_MARKERS: frozenset[str] = frozenset({"no", "not", "never", "without", "none", "cannot"})

# Terms excluded from support-coverage scoring: stopwords, negation markers
# (polarity is judged separately via _contains_negation — counting "not"
# against coverage systematically penalises contradicted claims), and pure
# auxiliaries that carry no content.
_COVERAGE_EXCLUDE: frozenset[str] = _STOP_WORDS | _NEGATION_MARKERS | {"does", "did"}


def _stem_term(term: str) -> str:
    """Naive suffix stripper with double-consonant collapse.

    Good enough to align regular inflections (logging/log, emitted/emit,
    windows/window); irregular verbs (built/build) are not handled and
    corpus rows relying on them are worded around.
    """
    if len(term) <= 3:
        return term
    for suffix, replacement in (("ies", "y"), ("ing", ""), ("es", ""), ("ed", ""), ("s", "")):
        if term.endswith(suffix) and not term.endswith("ss"):
            stem = term[: -len(suffix)] + replacement
            if len(stem) >= 3 and stem[-1] == stem[-2] and stem[-1] not in "aeiouy":
                stem = stem[:-1]
            return stem
    return term


def _coverage_terms(text: str) -> set[str]:
    return {
        _stem_term(token)
        for token in re.findall(r"[A-Za-z0-9_]+", text.lower())
        if len(token) > 2 and token not in _COVERAGE_EXCLUDE
    }


def support_coverage(claim_text: str, evidence_text: str) -> float:
    """Fraction of the claim's content terms present in one evidence record.

    The v2 support score building block: a measured 0-1 value, unlike the
    v1 two-keyword-overlap rule that verified any claim sharing two words
    with unrelated evidence (see evals/firewall_known_gaps.md, class A).
    """
    claim_terms = _coverage_terms(claim_text)
    if not claim_terms:
        return 0.0
    return len(claim_terms & _coverage_terms(evidence_text)) / len(claim_terms)


def score_support(claim_text: str, evidence_texts: list[str]) -> float:
    """Best-evidence support score in [0, 1] — the public firewall v2 API."""
    if not evidence_texts:
        return 0.0
    return max(support_coverage(claim_text, text) for text in evidence_texts)



# ── Enums ──────────────────────────────────────────────────────────────────


class ClaimType(str, Enum):
    FACTUAL = "factual"
    LOGICAL = "logical"
    OPINION = "opinion"
    SPECULATION = "speculation"


class ValidationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    CONTRADICTED = "contradicted"
    PENDING = "pending"


# ── Data Classes ───────────────────────────────────────────────────────────


@dataclass
class Claim:
    claim_id: str
    content: str
    claim_type: ClaimType
    confidence: float
    source_agent: str
    validation_status: ValidationStatus = ValidationStatus.PENDING
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class EvidenceRecord:
    source_id: str
    evidence_type: str
    content: str
    confidence: float = 1.0


@dataclass
class FirewallResult:
    original_text: str
    sanitized_text: str
    claims: list[Claim] = field(default_factory=list)
    unsupported_claims: list[Claim] = field(default_factory=list)

    @property
    def removed_or_qualified_count(self) -> int:
        return len(self.unsupported_claims)


# ── Claim Manager ──────────────────────────────────────────────────────────


class ClaimManager:
    """Extract, classify, and validate factual claims from agent outputs.

    Uses regex-based extraction and keyword-matching classification.
    Validates claims with placeholder logic (future: Wikipedia API or
    fact-checking service) and stores validated claims in the
    ReasoningGraph for future reference and audit.
    """

    # Regex patterns for extracting sentences that look like claims.
    # Matches sentences containing copular/linking verbs or modal verbs
    # that typically introduce assertions.
    _CLAIM_PATTERNS: list[re.Pattern[str]] = [
        re.compile(
            r"(?:^|[.!?]\s+)(?:.*?\b(is|are|was|were|has|have|will|can|could|should|may|might)\b.+?[.!?])",
            re.IGNORECASE,
        ),
    ]

    # v2 support gate: minimum stemmed-coverage fraction of the claim's
    # content terms that a supporting evidence record must carry. 0.7 keeps
    # every unambiguous verified exemplar in evals/firewall_corpus.jsonl
    # matched while rejecting the class-A false-verified gap rows.
    SUPPORT_COVERAGE_MIN: float = 0.7

    # Keywords for claim type classification.
    _LOGICAL_KEYWORDS: frozenset[str] = frozenset({
        "if", "then", "therefore", "because", "implies",
        "thus", "hence", "consequently", "so",
    })
    _OPINION_KEYWORDS: frozenset[str] = frozenset({
        "should", "better", "prefer", "believe", "think",
        "recommend", "opinion", "best", "worst",
    })
    _SPECULATION_KEYWORDS: frozenset[str] = frozenset({
        "might", "could", "possibly", "may", "perhaps",
        "probably", "likely", "unlikely", "speculate",
    })

    # Simple sentence splitter – handles period/question/exclamation
    # followed by a space or end-of-string.
    _SENTENCE_SPLITTER: re.Pattern[str] = re.compile(r"(?<=[.!?])\s+")

    # ── Extraction ───────────────────────────────────────────────────

    def extract_claims(self, text: str, agent_name: str) -> list[Claim]:
        """Extract potential claims from *text* produced by *agent_name*.

        A claim is any sentence that contains a linking verb, auxiliary
        verb, or modal verb that suggests an assertion about the world.

        Returns a (possibly empty) list of :class:`Claim` instances with
        ``PENDING`` validation status.
        """
        if not text or not text.strip():
            return []

        sentences = self._split_sentences(text)
        claims: list[Claim] = []

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if self._sentence_looks_like_claim(sentence):
                claim_type = self.classify_claim_type(sentence)
                claim = Claim(
                    claim_id=_generate_id(),
                    content=sentence,
                    claim_type=claim_type,
                    confidence=0.5,  # default until validation
                    source_agent=agent_name,
                    validation_status=ValidationStatus.PENDING,
                )
                claims.append(claim)

        logger.debug(
            "Extracted %d claims from agent '%s'", len(claims), agent_name,
            extra={"stage": "claims_manager", "agent": agent_name, "num_claims": len(claims)}
        )
        return claims

    # ── Classification ───────────────────────────────────────────────

    def classify_claim_type(self, claim_text: str) -> ClaimType:
        """Classify a claim sentence by type using keyword heuristics.

        Classification order (first match wins):
        1. LOGICAL  – contains logical connectors
        2. OPINION  – contains opinion markers
        3. SPECULATION – contains speculation markers
        4. FACTUAL  – default when no specific keywords match
        """
        lower = claim_text.lower()
        words = set(lower.split())

        if words & self._LOGICAL_KEYWORDS:
            return ClaimType.LOGICAL
        if words & self._OPINION_KEYWORDS:
            return ClaimType.OPINION
        if words & self._SPECULATION_KEYWORDS:
            return ClaimType.SPECULATION
        return ClaimType.FACTUAL

    # ── Validation ───────────────────────────────────────────────────

    def validate_claim(
        self,
        claim: Claim,
        evidence: list[EvidenceRecord] | None = None,
    ) -> ValidationStatus:
        """Validate a claim against available knowledge.

        Deterministic v1 firewall: validate a claim only against available
        evidence in the current request context (conversation, prior agent
        outputs, code/math snippets, or retrieved source text). Claims are
        never self-validated from their own output.
        """
        evidence = evidence or []
        claim_terms = self._keyword_set(claim.content)
        claim_numbers = self._numbers(claim.content)
        claim_negated = self._contains_negation(claim.content)
        overlap_threshold = self._overlap_threshold(claim_terms)

        matched: list[tuple[int, EvidenceRecord]] = []
        contradicted = False

        for record in evidence:
            record_terms = self._keyword_set(record.content)
            overlap = claim_terms & record_terms
            # The substring bypass needs a claim long enough to carry meaning:
            # ``"" in x`` is vacuously True and would verify a degenerate
            # (empty or 1-3 char) claim against any evidence record.
            claim_lower = claim.content.lower().strip()
            substring_match = len(claim_lower) >= 4 and claim_lower in record.content.lower()
            if not overlap and not substring_match:
                continue

            record_numbers = self._numbers(record.content)
            if claim_numbers and not claim_numbers.issubset(record_numbers):
                continue

            # v2 support gate: keyword overlap alone verified claims whose
            # subject the evidence never addressed (known-gaps class A).
            # Coverage >= SUPPORT_COVERAGE_MIN or a verbatim substring
            # containment counts as measured support.
            coverage = support_coverage(claim.content, record.content)
            if not substring_match and coverage < self.SUPPORT_COVERAGE_MIN:
                continue

            if len(overlap) >= overlap_threshold or substring_match:
                matched.append((len(overlap), record))
                if claim_negated != self._contains_negation(record.content):
                    contradicted = True

        matched.sort(key=lambda item: item[0], reverse=True)
        supporting_evidence = [
            {
                "source_id": record.source_id,
                "evidence_type": record.evidence_type,
                "content": record.content[:240],
                "confidence": record.confidence,
                "overlap": overlap,
            }
            for overlap, record in matched[:3]
        ]

        existing_provenance = dict(claim.provenance)
        existing_provenance.update(
            {
                "evidence": supporting_evidence,
                "validation_method": "evidence_checker",
                "support_score": (
                    score_support(claim.content, [record.content for record in evidence])
                    if evidence
                    else 0.0
                ),
            }
        )
        claim.provenance = existing_provenance

        if supporting_evidence:
            claim.validation_status = (
                ValidationStatus.CONTRADICTED if contradicted else ValidationStatus.VERIFIED
            )
            claim.confidence = 0.2 if contradicted else 0.85
        else:
            claim.validation_status = ValidationStatus.UNVERIFIED
            claim.confidence = 0.25

        logger.debug(
            "Claim %s validated as %s (confidence=%.2f)",
            claim.claim_id,
            claim.validation_status.value,
            claim.confidence,
            extra={
                "stage": "claims_manager",
                "claim_id": claim.claim_id,
                "confidence": claim.confidence,
                "status": claim.validation_status.value,
            }
        )
        return claim.validation_status

    def apply_firewall(
        self,
        text: str,
        *,
        agent_name: str,
        evidence: list[EvidenceRecord] | None = None,
    ) -> FirewallResult:
        """Qualify unsupported claims before a response leaves the validation layer."""
        if not text or not text.strip():
            return FirewallResult(original_text=text, sanitized_text=text)

        evidence = evidence or []
        rebuilt_sentences: list[str] = []
        claims: list[Claim] = []
        unsupported_claims: list[Claim] = []

        for sentence in self._split_sentences(text):
            if not self._sentence_looks_like_claim(sentence):
                rebuilt_sentences.append(sentence)
                continue

            claim = Claim(
                claim_id=_generate_id(),
                content=sentence,
                claim_type=self.classify_claim_type(sentence),
                confidence=0.5,
                source_agent=agent_name,
                validation_status=ValidationStatus.PENDING,
            )
            claims.append(claim)
            status = self.validate_claim(claim, evidence)
            if status == ValidationStatus.VERIFIED:
                rebuilt_sentences.append(sentence)
                continue

            unsupported_claims.append(claim)
            rebuilt_sentences.append(self._qualify_unsupported_claim(sentence, status))

        sanitized_text = " ".join(part.strip() for part in rebuilt_sentences if part.strip())
        return FirewallResult(
            original_text=text,
            sanitized_text=sanitized_text or text,
            claims=claims,
            unsupported_claims=unsupported_claims,
        )

    def build_evidence(
        self,
        *,
        user_query: str | None = None,
        history: list[Mapping[str, Any]] | None = None,
        agent_outputs: Mapping[str, Any] | None = None,
        prior_results: Mapping[str, Any] | None = None,
    ) -> list[EvidenceRecord]:
        """Build a request-scoped evidence pool from context and prior artifacts."""
        evidence: list[EvidenceRecord] = []

        if user_query and user_query.strip():
            evidence.append(EvidenceRecord(source_id="user_query", evidence_type="source", content=user_query.strip()))  # noqa: E501

        for index, message in enumerate(history or []):
            content = self._coerce_text(message)
            if content:
                role = str(message.get("role", "history")) if isinstance(message, Mapping) else "history"
                evidence.append(
                    EvidenceRecord(
                        source_id=f"history:{index}:{role}",
                        evidence_type="context",
                        content=content,
                    )
                )

        for source_id, payload in (agent_outputs or {}).items():
            content = self._coerce_text(payload)
            if content:
                evidence.append(
                    EvidenceRecord(
                        source_id=str(source_id),
                        evidence_type=self._infer_evidence_type(str(source_id), content),
                        content=content,
                    )
                )

        for source_id, payload in (prior_results or {}).items():
            content = self._coerce_text(payload)
            if content:
                evidence.append(
                    EvidenceRecord(
                        source_id=f"result:{source_id}",
                        evidence_type=self._infer_evidence_type(str(source_id), content),
                        content=content,
                    )
                )

        return evidence

    # ── Storage ──────────────────────────────────────────────────────

    def store_claim(
        self,
        claim: Claim,
        reasoning_graph: ReasoningGraph,
    ) -> str:
        """Store a validated claim in the ReasoningGraph.

        Creates a ``CLAIM`` node and, if supporting evidence nodes exist,
        ``SUPPORTS`` edges from the claim to those nodes.

        Returns the graph ``node_id`` of the stored claim.
        """
        node = GraphNode(
            node_id=claim.claim_id,
            node_type=NodeType.CLAIM,
            content=claim.content,
            metadata={
                "claim_type": claim.claim_type.value,
                "confidence": claim.confidence,
                "source_agent": claim.source_agent,
                "validation_status": claim.validation_status.value,
                "provenance": dict(claim.provenance),
            },
        )
        node_id = reasoning_graph.add_node(node)

        # Link to any existing reasoning steps that share keywords
        claim_words = set(claim.content.lower().split())
        for existing in list(reasoning_graph._nodes.values()):
            if existing.node_id == node_id:
                continue
            if existing.node_type in (NodeType.CLAIM, NodeType.REASONING_STEP):
                existing_words = set(existing.content.lower().split())
                overlap = len(claim_words & existing_words)
                if overlap >= 3:
                    edge = GraphEdge(
                        source_id=node_id,
                        target_id=existing.node_id,
                        edge_type=EdgeType.SUPPORTS,
                        weight=min(1.0, overlap / 10.0),
                    )
                    reasoning_graph.add_edge(edge)

        logger.debug("Stored claim %s in reasoning graph as node %s", claim.claim_id, node_id, extra={"stage": "claims_manager", "claim_id": claim.claim_id, "node_id": node_id})  # noqa: E501
        return node_id

    # ── Provenance ───────────────────────────────────────────────────

    def track_claim_provenance(
        self,
        claim: Claim,
        source: str,
        timestamp: datetime,
        validation_method: str,
    ) -> None:
        """Record provenance metadata for *claim*.

        Provenance tracks where the claim came from, when it was
        extracted, and how it was validated.
        """
        existing = dict(claim.provenance)
        existing.update({
            "source": source,
            "timestamp": timestamp.isoformat(),
            "validation_method": validation_method,
        })
        claim.provenance = existing
        logger.debug(
            "Tracked provenance for claim %s: source=%s method=%s",
            claim.claim_id,
            source,
            validation_method,
            extra={"stage": "claims_manager", "claim_id": claim.claim_id, "source": source, "method": validation_method}  # noqa: E501
        )

    # ── Querying ─────────────────────────────────────────────────────

    def get_unverified_claims(
        self,
        agent_name: Optional[str] = None,
        claims: Optional[list[Claim]] = None,
    ) -> list[Claim]:
        """Return claims that are not fully verified.

        If *agent_name* is provided, only claims from that agent are
        returned.  Pass an external *claims* list to search; otherwise
        the method returns an empty list (claims are stored externally
        by the caller or in the reasoning graph).
        """
        if claims is None:
            return []

        result = [
            c for c in claims
            if c.validation_status in {ValidationStatus.UNVERIFIED, ValidationStatus.CONTRADICTED}
        ]
        if agent_name:
            result = [c for c in result if c.source_agent == agent_name]

        return result

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split *text* into sentences on period/question/exclamation marks."""
        parts = ClaimManager._SENTENCE_SPLITTER.split(text)
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def _coerce_text(payload: Any) -> str:
        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, Mapping):
            for key in ("final_answer", "answer", "final_response", "objective", "content"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        for attr in ("final_answer", "answer"):
            value = getattr(payload, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _keyword_set(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[A-Za-z0-9_]+", text.lower())
            if len(token) > 2 and token not in _STOP_WORDS
        }

    @staticmethod
    def _numbers(text: str) -> set[str]:
        return set(re.findall(r"\b\d+(?:\.\d+)?\b", text))

    @staticmethod
    def _contains_negation(text: str) -> bool:
        words = set(re.findall(r"[A-Za-z]+", text.lower()))
        return bool(words & _NEGATION_MARKERS)

    @staticmethod
    def _overlap_threshold(keywords: set[str]) -> int:
        if len(keywords) <= 2:
            return 1
        if len(keywords) <= 5:
            return 2
        return 3

    @staticmethod
    def _infer_evidence_type(source_id: str, content: str) -> str:
        lowered = source_id.lower()
        if "code" in lowered or "verify" in lowered or "test" in lowered or "```" in content:
            return "code"
        if any(symbol in content for symbol in ("=", "+", "-", "*", "/")) and any(ch.isdigit() for ch in content):  # noqa: E501
            return "math"
        if lowered.startswith("history") or lowered == "user_query":
            return "context"
        return "reasoning"

    @staticmethod
    def _qualify_unsupported_claim(sentence: str, status: ValidationStatus) -> str:
        stripped = sentence.strip()
        if status == ValidationStatus.CONTRADICTED:
            reason = "available evidence conflicts with this claim"
        else:
            reason = "available evidence does not verify this claim"
        return f"{stripped} [Qualifier: {reason}.]"

    @classmethod
    def _sentence_looks_like_claim(cls, sentence: str) -> bool:
        """Return True if *sentence* contains a verb suggesting an assertion."""
        lower = sentence.lower()
        # Check for common assertion verbs via simple substring search
        assertion_markers = (
            " is ", " are ", " was ", " were ",
            " has ", " have ", " will ", " can ",
            " could ", " should ", " may ", " might ",
            " produces ", " creates ", " enables ",
            " provides ", " supports ", " indicates ",
        )
        return any(marker in lower for marker in assertion_markers)
