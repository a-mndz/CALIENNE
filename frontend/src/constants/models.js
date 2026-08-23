// Display aliases for the live strategy routes (verified 2026-08-22; the
// 2.5 Gemini line is unavailable to new keys and unli/* returns 401).
// Latencies stay "—" until measured — never fabricated.
export const INIT_MODELS = [
  { id: "gpt4o", name: "gpt-4o", latency: "—", active: true },
  { id: "claudesonnet5", name: "claude-sonnet-5", latency: "—", active: true },
  { id: "gemini37", name: "gemini-3.7-flash", latency: "—", active: true },
  { id: "gemini35lite", name: "gemini-3.5-flash-lite", latency: "—", active: true },
  { id: "gptoss120", name: "gpt-oss-120b", latency: "—", active: true },
  { id: "gptoss20", name: "gpt-oss-20b", latency: "—", active: false },
];
