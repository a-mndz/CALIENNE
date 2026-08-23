"""Golden-set + firewall-corpus integrity validation — gate G5 (blocking, zero-API).

Run: ``python -m evals.validate``

Checks:
  1. Manifest SHA-256 matches the referenced JSONL — an accidental in-place
     edit of a frozen version is a red build, not a mystery (dataset changes
     must bump to vN+1 and keep vN).
  2. Schema: every item has id, prompt_fingerprint, cluster_id, query, expect.
     Ids unique; fingerprints unique and equal to
     ``execution_replay.prompt_fingerprint(query)``.
  3. cluster_id present on every item (clustered standard errors — Miller
     recommendation 2; without it, uncertainty is understated >3x).
  4. Leakage: no golden query (or its normalised 40-char shingle) appears
     under prompts/, agents/, or docs/.
  5. Firewall corpus: schema and label vocabulary.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from orchestrator.execution_replay import prompt_fingerprint

EVALS_DIR = Path(__file__).resolve().parent
GOLDEN_DIR = EVALS_DIR / "golden"
REQUIRED_ITEM_FIELDS = ("id", "prompt_fingerprint", "cluster_id", "query", "expect")
CORPUS_LABELS = {"verified", "unverified", "contradicted"}
LEAK_SCAN_DIRS = ("prompts", "agents", "docs")
SHINGLE_LEN = 40


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_golden(version: str = "v1") -> tuple[list[dict], dict]:
    data_path = GOLDEN_DIR / f"{version}.jsonl"
    manifest_path = GOLDEN_DIR / "MANIFEST.json"
    if not data_path.exists():
        raise FileNotFoundError(f"golden set {data_path} not found")
    if not manifest_path.exists():
        raise FileNotFoundError(f"{manifest_path} not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    if manifest.get("version") != version:
        errors.append(f"manifest version {manifest.get('version')!r} != {version!r}")

    actual_hash = sha256_file(data_path)
    if manifest.get("sha256") != actual_hash:
        errors.append(
            f"golden set hash mismatch: manifest {manifest.get('sha256')!r} != "
            f"actual {actual_hash!r} — regenerate the manifest or bump the version"
        )

    items: list[dict] = []
    seen_ids: set[str] = set()
    seen_fps: set[str] = set()
    with open(data_path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            for field in REQUIRED_ITEM_FIELDS:
                if field not in item:
                    errors.append(f"{version}.jsonl:{line_no}: missing field {field!r}")
            if "id" in item:
                if item["id"] in seen_ids:
                    errors.append(f"{version}.jsonl:{line_no}: duplicate id {item['id']!r}")
                seen_ids.add(item["id"])
            if "query" in item and "prompt_fingerprint" in item:
                expected_fp = prompt_fingerprint(item["query"])
                if item["prompt_fingerprint"] != expected_fp:
                    errors.append(
                        f"{version}.jsonl:{line_no}: prompt_fingerprint "
                        f"{item['prompt_fingerprint']!r} != computed {expected_fp!r}"
                    )
                if item["prompt_fingerprint"] in seen_fps:
                    errors.append(
                        f"{version}.jsonl:{line_no}: duplicate prompt_fingerprint "
                        f"{item['prompt_fingerprint']!r} (duplicate query text?)"
                    )
                seen_fps.add(item["prompt_fingerprint"])
            if item.get("cluster_id") in (None, ""):
                errors.append(f"{version}.jsonl:{line_no}: empty cluster_id")
            items.append(item)

    if manifest.get("n") != len(items):
        errors.append(f"manifest n={manifest.get('n')} != {len(items)} items in file")

    return items, {"errors": errors, "manifest": manifest}


def check_leakage(items: list[dict]) -> list[str]:
    """Golden queries must not appear in the prompt/agent/doc surface.

    A golden query embedded in a system prompt is a leak: the model would be
    graded on text it was shown at training/prompt time. Checks the raw query
    and a normalised 40-char shingle so trivial reformatting is also caught.
    """
    errors: list[str] = []
    corpus_targets: list[Path] = []
    for dir_name in LEAK_SCAN_DIRS:
        root = Path(dir_name)
        if root.is_dir():
            corpus_targets.extend(
                p for p in root.rglob("*") if p.suffix in {".md", ".txt", ".xml", ".py", ".json"}
            )

    file_contents: dict[Path, str] = {
        p: p.read_text(encoding="utf-8", errors="ignore").lower() for p in corpus_targets
    }

    for item in items:
        query = str(item.get("query", ""))
        needle = " ".join(query.lower().split())
        shingle = needle[:SHINGLE_LEN]
        if len(shingle) < SHINGLE_LEN:
            continue  # too short to shingle meaningfully
        for path, content in file_contents.items():
            normalised_file = " ".join(content.split())
            if needle in normalised_file or shingle in normalised_file:
                errors.append(
                    f"leak: golden item {item.get('id')!r} query found in {path}"
                )
    return errors


def check_firewall_corpus() -> list[str]:
    corpus_path = EVALS_DIR / "firewall_corpus.jsonl"
    if not corpus_path.exists():
        # Absence is legal pre-capture; the G3 gate test skips with a marker.
        return []
    errors: list[str] = []
    seen: set[str] = set()
    with open(corpus_path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            claim = row.get("claim")
            label = row.get("expected_status")
            if not claim:
                errors.append(f"firewall_corpus.jsonl:{line_no}: missing claim")
            if label not in CORPUS_LABELS:
                errors.append(
                    f"firewall_corpus.jsonl:{line_no}: label {label!r} not in "
                    f"{sorted(CORPUS_LABELS)}"
                )
            key = (claim, json.dumps(row.get("evidence", []), sort_keys=True))
            if key in seen:
                errors.append(f"firewall_corpus.jsonl:{line_no}: duplicate row")
            seen.add(key)
    return errors


def main() -> int:
    errors: list[str] = []
    try:
        items, result = load_golden()
        errors.extend(result["errors"])
        errors.extend(check_leakage(items))
    except FileNotFoundError as exc:
        errors.append(str(exc))
    errors.extend(check_firewall_corpus())

    if errors:
        print("G5 VALIDATION FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("G5 validation passed (golden + firewall corpus integrity)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
