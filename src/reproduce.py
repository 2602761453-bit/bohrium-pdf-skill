#!/usr/bin/env python3
"""Bundle entrypoint: actually run the skill on the bundled sample PDF.

Produces:
  results/reading_order.json  the skill's structured output
  results/checks.json         per-page reading-order checks against the sample's labels
  results/run.log             stdout/stderr capture (written by the caller)

The sample PDF carries synthetic labels (LEFT-n / RIGHT-n / SINGLE-n) so the expected
order is knowable without a ground-truth answer key. Nothing here is pre-baked: every
number in results/ comes from this run.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample" / "synthetic-2col.pdf"
SKILL = ROOT / "scripts" / "read_columns.py"
RESULTS = ROOT / "results"

EXPECTED = {
    1: ["A Two Column Paper", "Abstract:", "The claim", "LEFT-1", "LEFT-2",
        "LEFT-3", "LEFT-4", "RIGHT-1", "RIGHT-2", "RIGHT-3", "RIGHT-4"],
    2: ["LEFT-5", "LEFT-6", "RIGHT-5", "RIGHT-6", "Figure 1",
        "LEFT-7", "LEFT-8", "RIGHT-7", "RIGHT-8"],
    3: ["SINGLE-1", "SINGLE-2", "SINGLE-3"],
}


def main() -> int:
    started_at = datetime.now(timezone.utc)
    RESULTS.mkdir(parents=True, exist_ok=True)
    if not SAMPLE.is_file():
        print(f"missing sample PDF: {SAMPLE}", file=sys.stderr)
        return 2

    out = RESULTS / "reading_order.json"
    skill_started = time.time()
    print(f"running skill on {SAMPLE.name}")
    proc = subprocess.run(
        [sys.executable, str(SKILL), "--pdf", "sample/synthetic-2col.pdf",
         "--out", "results/reading_order.json", "--case-id", "synthetic-2col"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    elapsed = round(time.time() - skill_started, 3)
    print(proc.stdout.strip())
    if proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)
    if proc.returncode != 0:
        print(f"skill failed with exit code {proc.returncode}", file=sys.stderr)
        return proc.returncode
    print(f"wrote results/reading_order.json in {elapsed}s")

    data = json.loads(out.read_text(encoding="utf-8"))
    body = [u for u in data["units"] if u["role"] == "body"]

    pages = {}
    all_ok = True
    for page, expected in EXPECTED.items():
        got = [u for u in body if u["page"] == page]
        texts = [u["text"].replace("\n", " ") for u in got]
        ok = len(texts) == len(expected) and all(
            text.startswith(prefix) for text, prefix in zip(texts, expected)
        )
        all_ok = all_ok and ok
        pages[f"page{page}"] = {
            "expected_order": expected,
            "actual_order": [t[:40] for t in texts],
            "exact_match": 1.0 if ok else 0.0,
            "units": len(texts),
        }
        print(f"page {page}: {'match' if ok else 'MISMATCH'} ({len(texts)} units)")

    checks = {
        "case_id": data.get("case_id"),
        "status": data["status"],
        "page_columns": data["layout"]["page_columns"],
        "pages": pages,
        "overall_exact_match": 1.0 if all_ok else 0.0,
        "header_footer_excluded": len(data["excluded"]),
        "warnings": data["warnings"],
        "uncertainty": data["uncertainty"],
        "wall_time_s": elapsed,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "total_wall_time_s": round((datetime.now(timezone.utc) - started_at).total_seconds(), 3),
    }
    (RESULTS / "checks.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"overall_exact_match={checks['overall_exact_match']}")
    print("wrote results/checks.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
