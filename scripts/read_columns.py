#!/usr/bin/env python3
"""Recover the reading order of a multi-column scientific PDF and keep page/block evidence.

Emits one JSON document with:
  - status: success | partial | unreadable
  - pages[]: per-page column layout and margins
  - units[]: body text blocks in recovered reading order, each with page (1-based),
    column index, normalized bbox and a stable unit id, so every paragraph can be
    traced back to a page and a block.
  - excluded[]: header/footer blocks kept separately instead of mixed into body.

Usage:
    python read_columns.py --pdf paper.pdf --out reading_order.json [--case-id X] [--md reading_order.md]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    import pymupdf
except ImportError:  # older installs expose the same API as `fitz`
    try:
        import fitz as pymupdf
    except ImportError:
        sys.stderr.write("PyMuPDF is required. Install with: python -m pip install pymupdf\n")
        raise SystemExit(3)

# Layout tuning. Fractions are of page width/height so they scale across page sizes.
HEADER_BAND = 0.075          # blocks fully above this height fraction are page furniture
FOOTER_BAND = 0.925          # blocks fully below this height fraction are page furniture
GUTTER_SEARCH = (0.18, 0.82)  # a column gutter cannot sit in the outer margins
MIN_GUTTER = 0.020           # narrowest accepted gutter, as a fraction of page width
GUTTER_COVER_RATIO = 0.40    # a gutter bin may be covered by at most this share of peak blocks
MAX_COLUMNS = 3
MIN_BODY_CHARS = 40          # below this a page is treated as having no usable text layer


def norm(value: float, total: float) -> float:
    return round(max(0.0, min(1.0, value / total)), 4)


def page_blocks(page) -> list[dict]:
    """Extract text blocks with normalized geometry, preserving characters exactly."""
    width, height = page.rect.width, page.rect.height
    blocks: list[dict] = []
    for raw in page.get_text("dict")["blocks"]:
        if raw.get("type") != 0:          # image, no text layer
            continue
        lines = []
        for line in raw["lines"]:
            text = "".join(span["text"] for span in line["spans"])
            if text.strip():
                lines.append(text)
        text = "\n".join(lines).strip()
        if not text:
            continue
        x0, y0, x1, y1 = raw["bbox"]
        blocks.append(
            {
                "text": text,
                "bbox": (x0, y0, x1, y1),
                "norm": [norm(x0, width), norm(y0, height), norm(x1, width), norm(y1, height)],
                "w": x1 - x0,
                "h": y1 - y0,
            }
        )
    return blocks


def classify_furniture(blocks: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split header/footer page furniture from the body."""
    body, furniture = [], []
    for block in blocks:
        _, y0, _, y1 = block["norm"]
        if y1 <= HEADER_BAND or y0 >= FOOTER_BAND:
            block["role"] = "header" if y1 <= HEADER_BAND else "footer"
            furniture.append(block)
        else:
            body.append(block)
    return body, furniture


def centre_x(block: dict) -> float:
    return (block["bbox"][0] + block["bbox"][2]) / 2


def find_gutter(blocks: list[dict], width: float) -> float | None:
    """Widest vertical band that few blocks cross, in page points.

    A spanning title or abstract covers the gutter, so coverage is compared with the
    busiest x position instead of demanding a perfectly empty band.
    """
    if len(blocks) < 6:
        return None
    bins = int(width)
    cover = [0] * bins
    for block in blocks:
        x0 = max(0, min(bins - 1, int(block["bbox"][0])))
        x1 = max(0, min(bins, int(block["bbox"][2])))
        for x in range(x0, x1):
            cover[x] += 1
    peak = max(cover) if cover else 0
    if peak < 3:
        return None
    limit = max(1, int(peak * GUTTER_COVER_RATIO))
    lo, hi = int(GUTTER_SEARCH[0] * width), int(GUTTER_SEARCH[1] * width)

    best: tuple[int, int] | None = None
    run_start: int | None = None
    for x in range(lo, min(hi, bins)):
        if cover[x] <= limit:
            if run_start is None:
                run_start = x
            if best is None or (x - run_start) > (best[1] - best[0]):
                best = (run_start, x)
        else:
            run_start = None
    if best is None or best[1] - best[0] < MIN_GUTTER * width:
        return None
    gutter = (best[0] + best[1]) / 2
    left = sum(1 for b in blocks if centre_x(b) < gutter)
    right = sum(1 for b in blocks if centre_x(b) >= gutter)
    if left < 3 or right < 3:
        return None
    return gutter


def detect_gutters(blocks: list[dict], width: float, depth: int = 0) -> list[float]:
    """Up to two gutters, found recursively so three-column pages also work."""
    if depth > 1 or len(blocks) < 8:
        return []
    gutter = find_gutter(blocks, width)
    if gutter is None:
        return []
    left = [b for b in blocks if centre_x(b) < gutter]
    right = [b for b in blocks if centre_x(b) >= gutter]
    nested = detect_gutters(left, width, depth + 1) + detect_gutters(right, width, depth + 1)
    return sorted([gutter] + nested)[: MAX_COLUMNS - 1]


def order_page(blocks: list[dict], width: float) -> tuple[list[dict], int]:
    """Return body blocks in reading order plus the detected column count."""
    gutters = detect_gutters(blocks, width)

    for block in blocks:
        crosses = any(block["bbox"][0] < g < block["bbox"][2] for g in gutters)
        block["column"] = -1 if crosses else sum(1 for g in gutters if centre_x(block) > g)

    ordered: list[dict] = []
    segment: list[dict] = []
    for block in sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0])):
        if block["column"] < 0:                     # spanning block separates segments
            ordered.extend(sorted(segment, key=lambda b: (b["column"], b["bbox"][1], b["bbox"][0])))
            segment = []
            ordered.append(block)
        else:
            segment.append(block)
    ordered.extend(sorted(segment, key=lambda b: (b["column"], b["bbox"][1], b["bbox"][0])))
    return ordered, max(1, len(gutters) + 1)


def build(pdf_path: Path, case_id: str | None) -> dict:
    document = pymupdf.open(pdf_path)
    sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    pages_out, units, excluded, warnings, uncertainty = [], [], [], [], []
    order = 0

    for pno, page in enumerate(document, start=1):
        width, height = page.rect.width, page.rect.height
        raw = page_blocks(page)
        body, furniture = classify_furniture(raw)
        body_chars = sum(len(b["text"]) for b in body)

        if body_chars < MIN_BODY_CHARS:
            text_len = len(page.get_text().strip())
            pages_out.append(
                {
                    "page": pno,
                    "size": [round(width, 2), round(height, 2)],
                    "columns": 0,
                    "body_blocks": 0,
                    "text_chars": text_len,
                    "note": "no usable text layer",
                }
            )
            warnings.append(
                f"page {pno}: only {text_len} characters extracted; treated as a scanned or "
                "image-only page and left out of the reading order"
            )
            uncertainty.append(
                f"page {pno}: content is not covered by this skill; OCR is out of scope"
            )
            continue

        ordered, columns = order_page(body, width)
        pages_out.append(
            {
                "page": pno,
                "size": [round(width, 2), round(height, 2)],
                "columns": columns,
                "body_blocks": len(ordered),
                "furniture_blocks": len(furniture),
                "text_chars": body_chars,
            }
        )

        for block in ordered:
            order += 1
            units.append(
                {
                    "unit_id": f"p{pno}-c{block['column']}-o{order:04d}",
                    "page": pno,
                    "column": block["column"],
                    "column_kind": "spanning" if block["column"] < 0 else "column",
                    "order": order,
                    "role": "body",
                    "text": block["text"],
                    "bbox_norm": block["norm"],
                }
            )
        for block in furniture:
            units.append(
                {
                    "unit_id": f"p{pno}-f-{len(units):04d}",
                    "page": pno,
                    "column": -1,
                    "column_kind": "furniture",
                    "order": None,
                    "role": block["role"],
                    "text": block["text"],
                    "bbox_norm": block["norm"],
                }
            )
            excluded.append({"page": pno, "role": block["role"], "text": block["text"]})

    document.close()

    if not units:
        status = "unreadable"
    elif warnings:
        status = "partial"
    else:
        status = "success"

    return {
        "case_id": case_id,
        "skill": "pdf-column-reader",
        "source": {
            "path": str(pdf_path),
            "sha256": sha,
            "pages": len(pages_out),
            "bytes": pdf_path.stat().st_size,
        },
        "status": status,
        "layout": {
            "header_band": HEADER_BAND,
            "footer_band": FOOTER_BAND,
            "max_columns": MAX_COLUMNS,
            "page_columns": {str(p["page"]): p["columns"] for p in pages_out},
        },
        "pages": pages_out,
        "units": units,
        "excluded": excluded,
        "warnings": warnings,
        "uncertainty": uncertainty,
        "reading_order_text": "\n".join(u["text"] for u in units if u["role"] == "body"),
    }


def to_markdown(result: dict) -> str:
    lines = [f"# Reading order: {result['case_id'] or result['source']['path']}", ""]
    for unit in result["units"]:
        if unit["role"] != "body":
            continue
        kind = "span" if unit["column"] < 0 else f"col {unit['column']}"
        lines.append(f"**[p{unit['page']} · {kind} · y={unit['bbox_norm'][1]:.3f}]**")
        lines.append(unit["text"])
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover multi-column reading order with evidence.")
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--md", type=Path, default=None)
    args = parser.parse_args()

    if not args.pdf.is_file():
        sys.stderr.write(f"input PDF not found: {args.pdf}\n")
        return 2
    try:
        result = build(args.pdf, args.case_id)
    except Exception as error:  # encrypted, corrupted, unsupported
        sys.stderr.write(f"failed to read {args.pdf}: {error}\n")
        return 4

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(to_markdown(result), encoding="utf-8")
    print(json.dumps({"status": result["status"], "units": len(result["units"]),
                      "pages": result["source"]["pages"], "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
