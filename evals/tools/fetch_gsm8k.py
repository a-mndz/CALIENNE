"""Fetch a deterministic GSM8K slice as an external golden arm.

External validity: the self-authored golden sets grade queries written by the
same person who wrote the system. GSM8K (grade-school math word problems) is
public, canonical, and numerically gradeable — a wrong answer cannot pass.

Rows come from the read-only HuggingFace datasets-server API (no auth, no
key). The slice is deterministic: every LENGTH-th row of the first OFFSET+
LIMIT*LENGTH rows, seeded by nothing — no shuffling, no drift between runs.

Usage: python -m evals.tools.fetch_gsm8k [--limit 50] [--stride 20]
Output: evals/golden/gsm8k_v1.jsonl (then register it in MANIFEST.json).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.execution_replay import prompt_fingerprint  # noqa: E402

API = "https://datasets-server.huggingface.co/rows"
DATASET = "openai/gsm8k"
CONFIG = "main"
SPLIT = "test"
FINAL_RE = re.compile(r"####\s*(-?[\d,]+(?:\.\d+)?)")

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"


def _final_answer(raw: str) -> float | None:
    match = FINAL_RE.search(raw or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def fetch(limit: int, stride: int, timeout: float = 60.0) -> list[dict]:
    """Pull rows from datasets-server, deterministically strided."""
    need = limit * stride
    rows: list[dict] = []
    offset = 0
    async_page = 100
    while len(rows) < need:
        page_len = min(async_page, need - offset)
        if page_len <= 0:
            break
        response = httpx.get(
            API,
            params={
                "dataset": DATASET,
                "config": CONFIG,
                "split": SPLIT,
                "offset": offset,
                "length": page_len,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        page_rows = payload.get("rows") or []
        if not page_rows:
            break
        for entry in page_rows:
            row = entry.get("row", {})
            answer_value = _final_answer(row.get("answer", ""))
            question = (row.get("question") or "").strip()
            if answer_value is None or not question:
                continue
            rows.append({"question": question, "answer": answer_value})
        offset += len(page_rows)
    return rows[: need][: limit * stride][::stride][:limit]


def build_jsonl(rows: list[dict]) -> str:
    lines = []
    for i, row in enumerate(rows, 1):
        item = {
            "id": f"m{i:03d}",
            "cluster_id": "gsm8k",
            "source": f"{DATASET}:{SPLIT}",
            "query": row["question"],
            "prompt_fingerprint": prompt_fingerprint(row["question"]),
            "expect": {
                "rubric": "v2",
                "checks": [{"type": "numeric", "value": row["answer"], "tolerance": 1e-6}],
            },
        }
        lines.append(json.dumps(item, sort_keys=True))
    return "".join(line + "\n" for line in lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="items to keep")
    parser.add_argument("--stride", type=int, default=20, help="take every Nth row")
    args = parser.parse_args(argv)

    print(f"fetching {args.limit} rows from {DATASET} (stride {args.stride})...")
    rows = fetch(args.limit, args.stride)
    if len(rows) < args.limit:
        print(f"error: only got {len(rows)} usable rows", file=sys.stderr)
        return 1

    out = GOLDEN_DIR / "gsm8k_v1.jsonl"
    out.write_text(build_jsonl(rows), encoding="utf-8")
    print(f"wrote {len(rows)} items to {out}")
    print("next: register in evals/golden/MANIFEST.json sets, then validate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
