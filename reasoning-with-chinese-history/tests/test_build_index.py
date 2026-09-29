import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_script(name):
    path = SKILL_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_index = load_script("build_index")


class BuildIndexTests(unittest.TestCase):
    def test_heading_and_author_comment_variants_are_classified(self):
        self.assertTrue(build_index.is_heading("*** 2.1　《三代世表》"))
        self.assertEqual(build_index.classify_role("太史公曰：故疑则传疑。¶"), "author_comment")

    def test_build_passages_preserves_lines_roles_and_original_text(self):
        passages = build_index.build_passages(FIXTURES)
        self.assertTrue(all(build_index.PAGE_PATTERN.sub("", item["text_original"]).replace("¶", "").strip() for item in passages))
        yellow_emperor = next(item for item in passages if "黄帝者" in item["text_original"])
        self.assertEqual(yellow_emperor["source_line_start"], 11)
        self.assertEqual(yellow_emperor["source_line_end"], 14)
        self.assertEqual(
            yellow_emperor["text_original"],
            "<pb:KR2a0001_tls_100-2a>黄帝者，¶\n少典之子，¶\n姓公孙，¶\n名曰轩辕。¶",
        )
        roles = {item["role"] for item in passages}
        self.assertTrue({"narrative", "author_comment", "annotation", "heading"}.issubset(roles))
        author_comment = next(item for item in passages if item["role"] == "author_comment")
        self.assertTrue(author_comment["text_original"].startswith("臣光曰"))
        annotation = next(item for item in passages if item["role"] == "annotation")
        self.assertTrue(annotation["text_original"].startswith("("))

    def test_cjk_search_terms_contains_unigrams_bigrams_and_ascii(self):
        terms = build_index.cjk_search_terms("进退 Alpha")
        tokens = terms.split()
        self.assertIn("进", tokens)
        self.assertIn("退", tokens)
        self.assertIn("进退", tokens)
        self.assertIn("alpha", tokens)

    def test_page_marker_flush_keeps_previous_page_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw_root = Path(temporary) / "shiji"
            raw_root.mkdir()
            (raw_root / "sample.txt").write_text(
                "#+TITLE: 史记\n<pb:old-page>¶\n第一段。¶\n　¶\n<pb:new-page>¶\n第二段。¶\n",
                encoding="utf-8",
            )
            passages = build_index.build_passages(Path(temporary))
        first = next(item for item in passages if "第一段" in item["text_original"])
        second = next(item for item in passages if "第二段" in item["text_original"])
        self.assertEqual(first["page_marker"], "old-page")
        self.assertEqual(second["page_marker"], "new-page")
        self.assertTrue(all(item["text_search"] for item in passages))

    def test_build_database_creates_fts_and_retrieves_cjk(self):
        passages = build_index.build_passages(FIXTURES)
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "search.sqlite3"
            build_index.build_database(passages, database)
            connection = sqlite3.connect(database)
            try:
                count = connection.execute(
                    "SELECT count(*) FROM passages_fts WHERE passages_fts MATCH ?", ("黄帝",)
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertGreaterEqual(count, 1)

    def test_require_fts5_reports_missing_module(self):
        class MissingFtsConnection:
            def execute(self, _statement):
                raise sqlite3.OperationalError("no such module: fts5")

        with self.assertRaisesRegex(RuntimeError, "FTS5"):
            build_index.require_fts5(MissingFtsConnection())


if __name__ == "__main__":
    unittest.main()
