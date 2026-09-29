import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile


SKILL_ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = SKILL_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch_corpus = load_script("fetch_corpus")


class FetchCorpusTests(unittest.TestCase):
    def test_temporary_converter_uses_verified_wheel_without_persistent_package(self):
        wheel_buffer = io.BytesIO()
        with zipfile.ZipFile(wheel_buffer, "w") as archive:
            archive.writestr(
                "opencc/__init__.py",
                "class OpenCC:\n"
                "    def __init__(self, config):\n"
                "        assert config == 't2s'\n"
                "    def convert(self, value):\n"
                "        return value.translate(str.maketrans({'記':'记','黃':'黄','後':'后'}))\n",
            )
        wheel_bytes = wheel_buffer.getvalue()
        expected_hash = hashlib.sha256(wheel_bytes).hexdigest()
        with mock.patch.object(fetch_corpus, "OPENCC_WHEEL_SHA256", expected_hash):
            with fetch_corpus.temporary_converter(lambda _url: wheel_bytes) as convert:
                self.assertEqual(convert("史記，黃帝之後。"), "史记，黄帝之后。")
        self.assertNotIn("opencc", __import__("sys").modules)

    def test_skill_does_not_retain_opencc_files(self):
        retained = [path for path in SKILL_ROOT.rglob("*") if path.is_file() and "opencc" in path.as_posix().lower()]
        self.assertEqual(retained, [])

    def test_convert_file_writes_only_simplified_text_and_preserves_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "traditional.txt"
            destination = root / "text" / "simplified.txt"
            source.write_text("史記\n黃帝之後\n", encoding="utf-8")

            def fake_convert(value):
                return value.translate(str.maketrans({"記": "记", "黃": "黄", "後": "后"}))

            record = fetch_corpus.convert_file(source, destination, fake_convert)
            self.assertEqual(destination.read_text(encoding="utf-8"), "史记\n黄帝之后\n")
            self.assertEqual(record["upstream_line_count"], 2)
            self.assertEqual(record["line_count"], 2)
            self.assertNotEqual(record["upstream_sha256"], record["sha256"])

    def test_ssl_context_loads_at_least_one_trusted_ca(self):
        context = fetch_corpus.build_ssl_context()
        self.assertGreater(context.cert_store_stats()["x509_ca"], 0)

    def test_validate_commit_requires_40_lowercase_hex_characters(self):
        commit = "a" * 40
        self.assertEqual(fetch_corpus.validate_commit(commit), commit)
        for invalid in ("a" * 39, "G" * 40, "A" * 40, "../escape"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    fetch_corpus.validate_commit(invalid)

    def test_safe_extract_rejects_parent_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                payload = b"escape"
                info = tarfile.TarInfo("../outside.txt")
                info.size = len(payload)
                bundle.addfile(info, io.BytesIO(payload))
            with tarfile.open(archive, "r:gz") as bundle:
                with self.assertRaises(ValueError):
                    fetch_corpus.safe_extract(bundle, Path(temporary) / "out")

    def test_build_manifest_records_hashes_and_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            text_root = destination / "text" / "shiji"
            text_root.mkdir(parents=True)
            source_file = text_root / "sample.txt"
            simplified_bytes = "史记转写".encode("utf-8")
            source_file.write_bytes(simplified_bytes)
            source = fetch_corpus.SourceSpec(
                slug="shiji",
                work="史记",
                author="司马迁",
                repo="https://github.com/kanripo/KR2a0001",
                branch="master",
                minimum_txt_files=1,
                license_name="CC BY-SA 4.0",
                license_basis_url="https://github.com/kanripo",
            )
            file_record = {
                "path": "text/shiji/sample.txt",
                "bytes": len(simplified_bytes),
                "sha256": hashlib.sha256(simplified_bytes).hexdigest(),
                "line_count": 1,
                "upstream_bytes": len("史記原文".encode("utf-8")),
                "upstream_sha256": hashlib.sha256("史記原文".encode("utf-8")).hexdigest(),
                "upstream_line_count": 1,
            }
            manifest = fetch_corpus.build_manifest(
                [(source, "a" * 40, [file_record])],
                generated_at="2026-09-27T00:00:00Z",
            )
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["text_variant"], "simplified-transcription")
            self.assertEqual(manifest["conversion"]["package"], "opencc-python-reimplemented")
            self.assertEqual(manifest["conversion"]["config"], "t2s")
            self.assertRegex(manifest["sources"][0]["commit"], r"^[0-9a-f]{40}$")
            recorded_hash = manifest["sources"][0]["files"][0]["sha256"]
            self.assertEqual(hashlib.sha256(simplified_bytes).hexdigest(), recorded_hash)
            self.assertTrue(manifest["sources"][0]["files"][0]["path"].startswith("text/"))
            canonical = json.dumps(
                {
                    "conversion": manifest["conversion"],
                    "sources": manifest["sources"],
                    "text_variant": manifest["text_variant"],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self.assertEqual(hashlib.sha256(canonical).hexdigest(), manifest["manifest_sha256"])


if __name__ == "__main__":
    unittest.main()
