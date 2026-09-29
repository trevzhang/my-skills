#!/usr/bin/env python3
"""Verify an exact quotation against one frozen simplified transcription file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def resolved_source(raw_root: Path, source_file: str) -> Path:
    root = Path(raw_root).resolve()
    candidate = (root / source_file).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Source path escapes corpus root: {source_file}")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def locate_lines(text: str, offset: int, quote: str) -> tuple[int, int]:
    start = text.count("\n", 0, offset) + 1
    end = start + quote.count("\n")
    return start, end


def verify_quote(
    raw_root: Path,
    source_file: str,
    quote: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict:
    path = resolved_source(raw_root, source_file)
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if not quote:
        return {"verified": False, "occurrences": 0, "matched_start_line": None, "matched_end_line": None, "reason": "empty quote"}
    search_text = text
    base_offset = 0
    if start_line is not None or end_line is not None:
        if start_line is None or end_line is None or start_line < 1 or end_line < start_line:
            raise ValueError("start_line and end_line must be a valid inclusive pair")
        lines = text.splitlines()
        search_text = "\n".join(lines[start_line - 1 : end_line])
        base_offset = sum(len(line) + 1 for line in lines[: start_line - 1])
    occurrences = search_text.count(quote)
    if occurrences == 0:
        return {"verified": False, "occurrences": 0, "matched_start_line": None, "matched_end_line": None, "reason": "exact quote not found"}
    relative_offset = search_text.find(quote)
    matched_start, matched_end = locate_lines(text, base_offset + relative_offset, quote)
    return {
        "verified": True,
        "occurrences": occurrences,
        "matched_start_line": matched_start,
        "matched_end_line": matched_end,
        "reason": "exact match",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text-root", dest="raw_root", type=Path, default=Path(__file__).resolve().parents[1] / "corpus/text")
    parser.add_argument("--source-file", required=True)
    parser.add_argument("--quote", required=True)
    parser.add_argument("--start-line", type=int)
    parser.add_argument("--end-line", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify_quote(args.raw_root, args.source_file, args.quote, args.start_line, args.end_line)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("verified" if result["verified"] else "not verified", result)
    raise SystemExit(0 if result["verified"] else 1)


if __name__ == "__main__":
    main()
