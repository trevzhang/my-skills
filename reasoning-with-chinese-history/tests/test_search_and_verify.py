import importlib.util
from pathlib import Path
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
search_corpus = load_script("search_corpus")
verify_citations = load_script("verify_citations")


class SearchAndVerifyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "search.sqlite3"
        passages = build_index.build_passages(FIXTURES)
        build_index.build_database(passages, self.database)

    def tearDown(self):
        self.temporary.cleanup()

    def test_search_returns_provenance_and_filters_work(self):
        results = search_corpus.search(self.database, "黄帝", "史记", 5, 1)
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["work"], "史记")
        self.assertIn("source_file", results[0])
        self.assertIn("source_line_start", results[0])

    def test_search_handles_fts_punctuation_safely(self):
        results = search_corpus.search(self.database, '黄帝" OR *', None, 5, 0)
        self.assertIsInstance(results, list)

    def test_verify_exact_quote_and_reject_one_character_change(self):
        quote = "<pb:KR2a0001_tls_100-2a>黄帝者，¶\n少典之子，¶"
        verified = verify_citations.verify_quote(
            FIXTURES,
            "shiji/KR2a0001_100.txt",
            quote,
            start_line=11,
            end_line=14,
        )
        self.assertTrue(verified["verified"])
        self.assertEqual(verified["matched_start_line"], 11)
        rejected = verify_citations.verify_quote(
            FIXTURES,
            "shiji/KR2a0001_100.txt",
            quote.replace("少典", "少皞"),
        )
        self.assertFalse(rejected["verified"])

    def test_verify_rejects_path_escape(self):
        with self.assertRaises(ValueError):
            verify_citations.verify_quote(FIXTURES, "../outside.txt", "text")


if __name__ == "__main__":
    unittest.main()
