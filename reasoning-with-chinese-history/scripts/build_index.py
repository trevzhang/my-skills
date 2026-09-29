#!/usr/bin/env python3
"""Parse simplified Kanseki transcriptions and build an auditable SQLite FTS5 index."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile


CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
ASCII_PATTERN = re.compile(r"[A-Za-z0-9_]+")
PAGE_PATTERN = re.compile(r"<pb:([^>]+)>")
PROPERTY_PATTERN = re.compile(r"^#\+PROPERTY:\s+([^\s]+)\s*(.*)$")
TITLE_PATTERN = re.compile(r"^#\+TITLE:\s*(.*)$")
NUMBERED_HEADING_PATTERN = re.compile(r"^\d+(?:\.\d+)+\s*[《〈].+[》〉]")
ORG_HEADING_PATTERN = re.compile(r"^\*{2,}\s+\d+(?:\.\d+)?(?:\s|　|[《〈])")


def cjk_search_terms(text: str) -> str:
    normalized = " ".join(text.split())
    terms = [normalized] if normalized else []
    for run in CJK_PATTERN.findall(text):
        terms.extend(run)
        terms.extend(run[index : index + 2] for index in range(len(run) - 1))
    terms.extend(word.lower() for word in ASCII_PATTERN.findall(text))
    return " ".join(dict.fromkeys(term for term in terms if term))


def is_heading(line: str) -> bool:
    stripped = line.strip()
    return bool(ORG_HEADING_PATTERN.match(stripped) or NUMBERED_HEADING_PATTERN.match(stripped))


def classify_role(text: str) -> str:
    stripped = text.strip()
    if is_heading(stripped):
        return "heading"
    without_page = PAGE_PATTERN.sub("", stripped).lstrip()
    if without_page.startswith(("臣光曰", "太史公曰")):
        return "author_comment"
    if without_page.startswith(("(", "（")) and without_page.rstrip("¶").endswith((")", "）")):
        return "annotation"
    return "narrative"


def clean_for_search(text: str) -> str:
    text = PAGE_PATTERN.sub(" ", text)
    text = text.replace("¶", " ")
    return cjk_search_terms(text)


def make_passage(
    work: str,
    author: str,
    section: str | None,
    juan: str | None,
    source_file: str,
    start_line: int,
    end_line: int,
    lines: list[str],
    page_marker: str | None,
    edition_note: str | None,
) -> dict:
    text_original = "\n".join(lines)
    role = classify_role(text_original)
    passage_seed = f"{source_file}:{start_line}:{end_line}:{role}".encode("utf-8")
    passage_id = hashlib.sha1(passage_seed).hexdigest()
    without_page = PAGE_PATTERN.sub("", text_original)
    return {
        "passage_id": passage_id,
        "work": work,
        "author": author,
        "section": section,
        "juan": juan,
        "era": None,
        "role": role,
        "source_file": source_file,
        "source_line_start": start_line,
        "source_line_end": end_line,
        "page_marker": page_marker,
        "edition_note": edition_note,
        "contains_inline_annotation": bool(
            ("(" in without_page and ")" in without_page)
            or ("（" in without_page and "）" in without_page)
        ),
        "text_original": text_original,
        "text_search": clean_for_search(text_original),
        "people": [],
        "places": [],
        "time_markers": [],
    }


def parse_file(path: Path, raw_root: Path, work: str, author: str) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    relative = path.relative_to(raw_root).as_posix()
    properties = {}
    title = work
    juan = None
    section = None
    page_marker = None
    edition_note = None
    passages = []
    buffer: list[str] = []
    buffer_start = 0
    buffer_role = None

    def flush(end_line: int) -> None:
        nonlocal buffer, buffer_start, buffer_role, edition_note
        if not buffer:
            return
        passages.append(
            make_passage(
                title,
                author,
                section,
                juan,
                relative,
                buffer_start,
                end_line,
                buffer,
                page_marker,
                edition_note,
            )
        )
        buffer = []
        buffer_start = 0
        buffer_role = None
        edition_note = None

    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        title_match = TITLE_PATTERN.match(stripped)
        property_match = PROPERTY_PATTERN.match(stripped)
        if title_match:
            flush(number - 1)
            title = title_match.group(1).strip() or work
            continue
        if property_match:
            flush(number - 1)
            properties[property_match.group(1)] = property_match.group(2).strip()
            if property_match.group(1) == "JUAN":
                juan = property_match.group(2).strip() or juan
            continue
        if stripped.startswith("# src:"):
            flush(number - 1)
            edition_note = stripped[1:].strip()
            continue
        if stripped.startswith("#") and not stripped.startswith("#+"):
            flush(number - 1)
            continue
        markers = PAGE_PATTERN.findall(line)
        visible_text = PAGE_PATTERN.sub("", line).replace("¶", "").strip()
        if not visible_text:
            flush(number - 1)
            if markers:
                page_marker = markers[-1]
            continue
        if markers:
            page_marker = markers[-1]
        current_role = classify_role(line)
        if is_heading(line):
            flush(number - 1)
            section = stripped
            passages.append(
                make_passage(
                    title,
                    author,
                    section,
                    juan,
                    relative,
                    number,
                    number,
                    [line],
                    page_marker,
                    edition_note,
                )
            )
            edition_note = None
            continue
        if buffer and (current_role != buffer_role or sum(len(item) for item in buffer) + len(line) > 600):
            flush(number - 1)
        if not buffer:
            buffer_start = number
            buffer_role = current_role
        buffer.append(line)
    flush(len(lines))
    return passages


def build_passages(raw_root: Path) -> list[dict]:
    raw_root = Path(raw_root)
    metadata = {
        "shiji": ("史记", "司马迁"),
        "zizhi-tongjian": ("资治通鉴", "司马光"),
    }
    passages = []
    for path in sorted(raw_root.rglob("*.txt")):
        slug = path.relative_to(raw_root).parts[0]
        work, author = metadata.get(slug, (slug, ""))
        passages.extend(parse_file(path, raw_root, work, author))
    return sorted(passages, key=lambda item: item["passage_id"])


def require_fts5(connection) -> None:
    try:
        connection.execute("CREATE VIRTUAL TABLE temp.fts5_check USING fts5(value)")
        connection.execute("DROP TABLE temp.fts5_check")
    except sqlite3.OperationalError as error:
        raise RuntimeError("SQLite FTS5 support is required") from error


def build_database(passages: list[dict], database: Path) -> None:
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkstemp(prefix=f".{database.name}-", dir=database.parent)[1])
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    try:
        require_fts5(connection)
        connection.executescript(
            """
            CREATE TABLE passages (
              passage_id TEXT PRIMARY KEY,
              work TEXT NOT NULL,
              author TEXT NOT NULL,
              section TEXT,
              juan TEXT,
              era TEXT,
              role TEXT NOT NULL,
              source_file TEXT NOT NULL,
              source_line_start INTEGER NOT NULL,
              source_line_end INTEGER NOT NULL,
              page_marker TEXT,
              edition_note TEXT,
              contains_inline_annotation INTEGER NOT NULL,
              text_original TEXT NOT NULL,
              text_search TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE passages_fts USING fts5(
              passage_id UNINDEXED,
              work,
              section,
              juan,
              text_search,
              tokenize='unicode61'
            );
            CREATE INDEX passages_source_lines
              ON passages(source_file, source_line_start, source_line_end);
            """
        )
        for item in sorted(passages, key=lambda record: record["passage_id"]):
            connection.execute(
                "INSERT INTO passages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item["passage_id"], item["work"], item["author"], item["section"],
                    item["juan"], item["era"], item["role"], item["source_file"],
                    item["source_line_start"], item["source_line_end"], item["page_marker"],
                    item["edition_note"], int(item["contains_inline_annotation"]),
                    item["text_original"], item["text_search"],
                ),
            )
            connection.execute(
                "INSERT INTO passages_fts VALUES (?, ?, ?, ?, ?)",
                (item["passage_id"], item["work"], item["section"], item["juan"], item["text_search"]),
            )
        connection.commit()
    finally:
        connection.close()
    temporary.replace(database)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    passages = build_passages(args.text_root)
    if not passages:
        raise SystemExit("No passages were parsed")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    jsonl = args.output_dir / "passages.jsonl"
    temporary_jsonl = jsonl.with_suffix(".jsonl.tmp")
    with temporary_jsonl.open("w", encoding="utf-8") as handle:
        for passage in passages:
            handle.write(json.dumps(passage, ensure_ascii=False, sort_keys=True) + "\n")
    temporary_jsonl.replace(jsonl)
    build_database(passages, args.output_dir / "search.sqlite3")
    counts = {}
    for passage in passages:
        counts[passage["work"]] = counts.get(passage["work"], 0) + 1
    print(json.dumps({"passages": len(passages), "works": counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
