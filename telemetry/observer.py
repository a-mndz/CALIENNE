import logging
from typing import Dict

logger = logging.getLogger("aetheris.Telemetry")

# Pricing rates per 1,000,000 tokens (USD). Refreshed 2026-08-22 against
# provider price pages (google: ai.google.dev, groq gpt-oss: console.groq.com,
# anthropic claude-5: platform.claude.com — see research/AETHERIS_RESEARCH_
# 2026-08-21.md). Substring match on the served model id, most-specific key
# first ("gpt-4o-mini" must precede "gpt-4o"). "default" applies to unknown
# models — costs for those are approximations, not measurements.
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # Live-verified 2026-08-22: the 2.5 line is unavailable to new keys; the
    # 3.x line prices verified against ai.google.dev/gemini-api/docs/pricing
    # (3.6/3.7 intro rates run through 2026-12-31).
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
    "gemini-3.7-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.6-flash": {"input": 0.75, "output": 3.75},
    "gemini-pro-latest": {"input": 2.00, "output": 12.00},
    "gpt-oss-120b": {"input": 0.15, "output": 0.60},
    "gpt-oss-20b": {"input": 0.075, "output": 0.30},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "default": {"input": 0.10, "output": 0.20}
}

def estimate_cost_usd(model_string: str, input_tokens: int, output_tokens: int) -> float:
    """Cost for a call from the pricing table matched on model substring.

    Derived from measured token counts — never from a predicted value.
    """
    model_key = "default"
    for key in MODEL_PRICING:
        if key in model_string.lower():
            model_key = key
            break
    rates = MODEL_PRICING[model_key]
    return ((input_tokens / 1_000_000) * rates["input"]) + ((output_tokens / 1_000_000) * rates["output"])


class TelemetryObserver:
    """
    Monitors execution latencies, token consumption metrics, and query costs.
    """
    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.accumulated_cost_usd = 0.0
        self.transaction_count = 0
        self.total_latency_s = 0.0
        self.successful_calls = 0
        self.failed_calls = 0
        # Tier 0.5: this was seeded with 24 fabricated activity points so the
        # dashboard looked alive before any real request. Empty until reality
        # supplies data — do not re-seed.
        self.sparkline_history: list[float] = []

    def track_usage(self, model_string: str, input_tokens: int, output_tokens: int, latency_s: float = 0.0, success: bool = True):  # noqa: E501
        """Calculates exact usage costs and aggregates telemetry data."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.transaction_count += 1
        if success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1
        if latency_s > 0:
            self.total_latency_s += latency_s

        # Match model signature to pricing cards
        cost = estimate_cost_usd(model_string, input_tokens, output_tokens)
        self.accumulated_cost_usd += cost

        activity_point = min(100.0, max(15.0, (input_tokens + output_tokens) / 50.0))
        self.sparkline_history.append(round(activity_point, 1))
        if len(self.sparkline_history) > 24:
            self.sparkline_history.pop(0)

        logger.info(
            f"[METRIC] Model: {model_string} | Tokens: I={input_tokens}/O={output_tokens} | Cost: ${cost:.6f}"
        )

    def get_telemetry_dict(self) -> dict:
        """Return comprehensive live telemetry metrics for status endpoints.

        Fields with no observations yet are ``None`` — never a plausible-
        looking constant. Fabricated fallbacks (1.2s latency, 99.4% success)
        made the dashboard lie before the first real request.
        """
        avg_resp = (
            round(self.total_latency_s / self.transaction_count, 1)
            if self.transaction_count > 0 and self.total_latency_s > 0
            else None
        )
        success_rate = (
            round((self.successful_calls / self.transaction_count) * 100.0, 1)
            if self.transaction_count > 0
            else None
        )
        return {
            "total_calls": self.transaction_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cost_usd": round(self.accumulated_cost_usd, 6),
            "avg_response_s": str(avg_resp) if avg_resp is not None else None,
            "success_rate": str(success_rate) if success_rate is not None else None,
            "sparkline": list(self.sparkline_history),
        }

    def print_session_report(self):
        """Outputs summary metrics for system auditing."""
        logger.info("=" * 50)
        logger.info("aetheris TELEMETRY SESSION REPORT")
        logger.info("=" * 50)
        logger.info("Total Model Calls:   %d", self.transaction_count)
        logger.info("Total Input Tokens:  %d", self.total_input_tokens)
        logger.info("Total Output Tokens: %d", self.total_output_tokens)
        logger.info("Total Cost (USD):    $%.6f", self.accumulated_cost_usd)
        logger.info("=" * 50)

# Global Telemetry Observer
observer = TelemetryObserver()
