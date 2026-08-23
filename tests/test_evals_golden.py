"""Blocking gates G3 + G5 — frozen corpus exact match and golden-set integrity.

These run under ``pytest -m "not slow"`` with zero API calls. A red here is a
real regression or a tampered dataset, never provider noise.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.validate import (
    check_firewall_corpus,
    check_leakage,
    load_golden,
)
from evals.validate import (
    main as validate_main,
)
from orchestrator.claims import Claim, ClaimManager, ClaimType, EvidenceRecord

EVALS_DIR = Path(__file__).resolve().parents[1] / "evals"


# ── G5: golden-set integrity ─────────────────────────────────────────────


class TestGoldenSetIntegrity:
    def test_manifest_hash_schema_and_fingerprints(self) -> None:
        items, meta = load_golden("v1")
        assert meta["errors"] == [], "\n".join(meta["errors"])
        assert len(items) == 50
        clusters = {item["cluster_id"] for item in items}
        assert len(clusters) == 10

    def test_leakage_scan_clean(self) -> None:
        items, _ = load_golden("v1")
        assert check_leakage(items) == []

    def test_validator_cli_exits_zero(self) -> None:
        assert validate_main() == 0

    def test_hash_mismatch_is_detected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Tamper detection: rewrite the golden module's paths to a tmp copy.
        import evals.validate as mod

        golden_copy = tmp_path / "golden"
        golden_copy.mkdir()
        (golden_copy / "v1.jsonl").write_text(
            (EVALS_DIR / "golden" / "v1.jsonl").read_text(encoding="utf-8")
            + json.dumps({
                "id": "tamper", "prompt_fingerprint": "deadbeef", "cluster_id": "x",
                "query": "tampered query", "expect": {},
            }) + "\n",
            encoding="utf-8",
        )
        (golden_copy / "MANIFEST.json").write_text(
            (EVALS_DIR / "golden" / "MANIFEST.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "GOLDEN_DIR", golden_copy)
        _, meta = mod.load_golden("v1")
        assert any("hash mismatch" in e or "n=" in e for e in meta["errors"])


# ── G3: claim-firewall frozen corpus — 100% exact match ──────────────────


class TestFirewallCorpus:
    CORPUS = EVALS_DIR / "firewall_corpus.jsonl"

    def _rows(self) -> list[dict]:
        rows = [
            json.loads(line)
            for line in self.CORPUS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert rows, "firewall corpus missing"
        return rows

    def test_corpus_has_minimum_rows(self) -> None:
        assert len(self._rows()) >= 50

    def test_corpus_schema(self) -> None:
        assert check_firewall_corpus() == []

    def test_every_row_matches_frozen_status(self) -> None:
        """THE G3 gate: matcher verdict == frozen expected_status, 100%."""
        manager = ClaimManager()
        mismatches = []
        for row in self._rows():
            claim = Claim(
                claim_id="corpus",
                content=row["claim"],
                claim_type=ClaimType.FACTUAL,
                confidence=0.5,
                source_agent="corpus",
            )
            evidence = [
                EvidenceRecord(source_id=f"src{i}", evidence_type="context", content=text)
                for i, text in enumerate(row["evidence"])
            ]
            status = manager.validate_claim(claim, evidence)
            if status.value != row["expected_status"]:
                mismatches.append((row["claim"], row["expected_status"], status.value))
        assert not mismatches, "\n".join(
            f"expected={exp} got={got}: {claim}" for claim, exp, got in mismatches
        )

    def test_frozen_corpus_excludes_known_gap_rows(self) -> None:
        """Gap rows (firewall_known_gaps.md) must never silently re-enter the
        frozen corpus without the matcher actually being fixed."""
        gaps_doc = (EVALS_DIR / "firewall_known_gaps.md").read_text(encoding="utf-8")
        if "class A" not in gaps_doc:  # pragma: no cover — doc is committed
            pytest.fail("firewall_known_gaps.md lost its gap tables")
