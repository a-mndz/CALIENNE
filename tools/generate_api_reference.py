#!/usr/bin/env python3
"""Generate docs/api.md from the FastAPI OpenAPI schema.

Canonical API reference (Phase 8). The manual route documentation kept
drifting from server.py; this renders docs/api.md directly from
app.openapi() so the doc cannot diverge.

Usage:
    python tools/generate_api_reference.py           # rewrite docs/api.md
    python tools/generate_api_reference.py --check   # exit 1 if stale (CI)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "docs" / "api.md"

HEADER = """\
# calienne API Reference

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: python tools/generate_api_reference.py -->

Generated from the live FastAPI OpenAPI schema (`app.openapi()` in
`server.py`). Run `python tools/generate_api_reference.py` after changing
routes; CI fails if this file is stale.
"""


def _schema_name(schema: dict) -> str:
    ref = schema.get("$ref", "")
    if ref:
        return f"`{ref.rsplit('/', 1)[-1]}`"
    t = schema.get("type")
    if t == "array":
        return f"array of {_schema_name(schema.get('items', {}))}"
    return f"`{t}`" if t else "—"


def _render(spec: dict) -> str:
    lines = [HEADER]
    info = spec.get("info", {})
    lines.append(f"**Title:** {info.get('title', '?')}  ")
    lines.append(f"**Version:** {info.get('version', '?')}\n")

    for path in sorted(spec.get("paths", {})):
        ops = spec["paths"][path]
        for method in ("get", "post", "put", "patch", "delete"):
            op = ops.get(method)
            if op is None:
                continue
            lines.append(f"## `{method.upper()} {path}`\n")
            summary = op.get("summary") or op.get("operationId", "")
            if summary:
                lines.append(f"{summary}\n")
            desc = (op.get("description") or "").strip()
            if desc:
                lines.append(f"{desc}\n")

            params = op.get("parameters", [])
            if params:
                lines.append("**Parameters:**\n")
                for p in params:
                    req = " (required)" if p.get("required") else ""
                    lines.append(
                        f"- `{p['name']}` ({p.get('in', '?')}){req}: "
                        f"{_schema_name(p.get('schema', {}))}"
                    )
                lines.append("")

            body = op.get("requestBody", {})
            body_schema = (
                body.get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            if body_schema:
                lines.append(f"**Request body:** {_schema_name(body_schema)}\n")

            responses = op.get("responses", {})
            resp_lines = []
            for code in sorted(responses):
                r = responses[code]
                r_schema = (
                    r.get("content", {})
                    .get("application/json", {})
                    .get("schema")
                )
                shape = f" — {_schema_name(r_schema)}" if r_schema else ""
                resp_lines.append(
                    f"- `{code}` {r.get('description', '')}{shape}"
                )
            if resp_lines:
                lines.append("**Responses:**\n")
                lines.extend(resp_lines)
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if docs/api.md is out of date.",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(REPO_ROOT))
    from server import app  # noqa: E402

    rendered = _render(app.openapi())

    if args.check:
        existing = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if existing != rendered:
            sys.stderr.write(
                "docs/api.md is stale. Regenerate with: "
                "python tools/generate_api_reference.py\n"
            )
            return 1
        return 0

    OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
