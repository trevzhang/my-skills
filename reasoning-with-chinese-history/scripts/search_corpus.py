#!/usr/bin/env python3
"""Search the local historical corpus with provenance-rich results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sqlite3


CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
ASCII_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def query_tokens(query: str) -> list[str]:
    tokens = []
    for run in CJK_PATTERN.findall(query):
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
        if len(run) == 1:
            tokens.append(run)
    tokens.extend(word.lower() for word in ASCII_PATTERN.findall(query))
    return list(dict.fromkeys(token for token in tokens if token))


def fts_query(query: str) -> str:
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in query_tokens(query))


def row_to_dict(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["contains_inline_annotation"] = bool(result["contains_inline_annotation"])
    return result


def search(database: Path, query: str, work: str | None = None, limit: int = 20, context: int = 1) -> list[dict]:
    expression = fts_query(query)
    if not expression:
        return []
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        sql = """
            SELECT p.*, bm25(passages_fts) AS rank
            FROM passages_fts
            JOIN passages p ON p.passage_id = passages_fts.passage_id
            WHERE passages_fts MATCH ?
        """
        parameters: list[object] = [expression]
        if work:
            sql += " AND p.work = ?"
            parameters.append(work)
        sql += " ORDER BY rank, p.source_file, p.source_line_start LIMIT ?"
        parameters.append(max(1, limit))
        primary = [row_to_dict(row) for row in connection.execute(sql, parameters)]
        if context <= 0:
            return primary
        expanded = {}
        for item in primary:
            neighbors = connection.execute(
                """
                SELECT p.*, NULL AS rank
                FROM passages p
                WHERE p.source_file = ?
                  AND p.source_line_start >= ?
                  AND p.source_line_start <= ?
                ORDER BY p.source_line_start
                """,
                (
                    item["source_file"],
                    max(1, item["source_line_start"] - context * 700),
                    item["source_line_end"] + context * 700,
                ),
            )
            candidate_neighbors = [row_to_dict(row) for row in neighbors]
            ordered_ids = [neighbor["passage_id"] for neighbor in candidate_neighbors]
            try:
                center = ordered_ids.index(item["passage_id"])
            except ValueError:
                center = 0
            selected = candidate_neighbors[max(0, center - context) : center + context + 1]
            for neighbor in selected:
                expanded.setdefault(neighbor["passage_id"], neighbor)
            expanded[item["passage_id"]] = item
        return sorted(expanded.values(), key=lambda record: (record["source_file"], record["source_line_start"]))
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--database", type=Path, default=Path(__file__).resolve().parents[1] / "corpus/index/search.sqlite3")
    parser.add_argument("--work", choices=["史记", "资治通鉴"])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--context", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = search(args.database, args.query, args.work, args.limit, args.context)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    for item in results:
        location = f"{item['source_file']}:{item['source_line_start']}-{item['source_line_end']}"
        print(f"[{item['work']} | {item.get('section') or item.get('juan') or '未标章节'} | {item['role']} | {location}]")
        print(item["text_original"])
        print()


if __name__ == "__main__":
    main()
