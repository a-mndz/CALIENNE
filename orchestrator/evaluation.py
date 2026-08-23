"""
aetheris — Adaptive Multi-Model Reasoning Orchestrator
Validation arbitration & synthesis judge.

Invokes a dedicated judge model to score logical consistency between
two competing agent outputs and formulate an authoritative consensus.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from agents.parser import parse_and_repair
from agents.prompt_utils import assemble_synthesizer_prompt
from api_gateway.rate_limiter import AsyncAPIGateway, ProviderPool
from api_gateway.strategy import ProviderStrategy
from core.schemas import aetherisOutput

logger = logging.getLogger("aetheris.Orchestrator.Evaluation")


def _delimit_safe(value: str) -> str:
    """JSON-encode untrusted text for embedding in a delimited prompt section.

    ``json.dumps`` escapes quotes and backslashes but leaves ``<``, ``>``, and
    ``&`` literal, so text containing e.g. ``</user_query>`` would close the
    delimited section and inject instructions into the judge prompt. Escaping
    them as JSON unicode escapes keeps the value decodable while guaranteeing
    the closing delimiter can never appear in the untrusted span.
    """
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


async def arbitrate_and_synthesize(
    query: str,
    answer_a: str,
    answer_b: str,
    gateway: AsyncAPIGateway,
    strategy: ProviderStrategy,
    pool: Optional[ProviderPool] = None,
    lessons: str = "",
    history: list[dict[str, str]] | None = None,
) -> aetherisOutput | dict:
    """
    Invokes the synthesizer judge to score logical consistency
    and formulate the authoritative consensus response.

    Parameters
    ----------
    query:
        The original user query.
    answer_a:
        Logician agent's answer.
    answer_b:
        Creative agent's answer.
    gateway:
        The async API gateway for making model calls.
    strategy:
        Provider strategy for model selection.
    pool:
        Optional provider pool for health tracking.  If omitted the
        gateway's internal default pool is used (not recommended).
    lessons:
        Historical loop-failure lessons to inject.
    """
    # JSON-encode untrusted content and escape the delimiter-significant
    # characters json.dumps leaves literal (< > &) so user input cannot
    # close the <user_query>/<logician_argument>/... sections and inject
    # judge instructions. See _delimit_safe.
    safe_query = _delimit_safe(query)
    safe_answer_a = _delimit_safe(answer_a)
    safe_answer_b = _delimit_safe(answer_b)
    safe_lessons = _delimit_safe(lessons if lessons else "None. This is the primary loop execution.")

    evaluation_prompt = f"""\
You are the Senior Synthesizer Arbiter. Your task is to evaluate two competing reasoning
patterns from agent nodes, resolve any logical discrepancies, and output a singular
authoritative response.

<user_query>
{safe_query}
</user_query>

<logician_argument>
{safe_answer_a}
</logician_argument>

<creative_argument>
{safe_answer_b}
</creative_argument>

<historic_lessons>
{safe_lessons}
</historic_lessons>

INSTRUCTIONS:
1. Resolve contradictions logically.
2. Formulate your 'final_answer' as a comprehensive, conversational response (like a helpful AI assistant). You MUST include and discuss any valid alternatives or trade-offs proposed by the Creative agent in your final answer! Do not truncate them.
3. Provide validation_score from 0.0 to 10.0 indicating overall logical consistency.
4. State structural disagreements clearly in 'disagreement_notes'.

Output strictly in raw JSON following the aetherisOutput schema layout:
{{
  "final_answer": "<your_synthesized_response>",
  "overall_confidence": "High/Medium/Low",
  "overall_bias_risk": "Low/Medium/High",
  "disagreement_notes": ["Note 1", "Note 2"],
  "validation_score": 9.5
}}
"""  # noqa: E501

    logger.info("Calling Synthesizer validation judge...")
    system_prompt = assemble_synthesizer_prompt(strategy.mode.value)

    # The judge synthesizes two full answers into one: the 4096-token default
    # truncated live responses mid-JSON, losing final_answer (which models
    # emit last, after their reasoning_steps) — found on the first live
    # capture, 2026-08-22.
    raw_judge_output = await gateway.execute_with_fallback(
        prompt=evaluation_prompt,
        system_prompt=system_prompt,
        role="judge",
        strategy=strategy,
        pool=pool,
        history=history,
        max_tokens=8192,
    )

    return parse_and_repair(raw_judge_output, aetherisOutput)
