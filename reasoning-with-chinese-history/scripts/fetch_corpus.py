#!/usr/bin/env python3
"""Download Kanseki snapshots, convert them to simplified Chinese, and record provenance."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib
import json
from pathlib import Path
import re
import shutil
import ssl
import stat
import sys
import tarfile
import tempfile
from typing import NamedTuple
from urllib.request import Request, urlopen
from datetime import datetime, timezone
import uuid
import zipfile


class SourceSpec(NamedTuple):
    slug: str
    work: str
    author: str
    repo: str
    branch: str
    minimum_txt_files: int
    license_name: str
    license_basis_url: str


SOURCES = [
    SourceSpec(
        slug="shiji",
        work="史记",
        author="司马迁",
        repo="https://github.com/kanripo/KR2a0001",
        branch="master",
        minimum_txt_files=14,
        license_name="CC BY-SA 4.0",
        license_basis_url="https://github.com/kanripo",
    ),
    SourceSpec(
        slug="zizhi-tongjian",
        work="资治通鉴",
        author="司马光",
        repo="https://github.com/kanripo/KR2b0007",
        branch="master",
        minimum_txt_files=296,
        license_name="CC BY-SA 4.0",
        license_basis_url="https://github.com/kanripo",
    ),
]

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
USER_AGENT = "reasoning-with-chinese-history-skill/1.0"
OPENCC_PACKAGE = "opencc-python-reimplemented"
OPENCC_VERSION = "0.1.7"
OPENCC_CONFIG = "t2s"
OPENCC_WHEEL_SHA256 = "41b3b92943c7bed291f448e9c7fad4b577c8c2eae30fcfe5a74edf8818493aa6"
OPENCC_WHEEL_URL = "https://files.pythonhosted.org/packages/30/6b/055b7806f320cc8f2cdf23c5f70221c0dc1683fca9ffaf76dfc2ad4b91b6/opencc_python_reimplemented-0.1.7-py2.py3-none-any.whl"


def validate_commit(value: str) -> str:
    value = value.strip()
    if not COMMIT_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid Git commit: {value!r}")
    return value


def build_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if context.cert_store_stats()["x509_ca"] > 0:
        return context
    candidates = [
        Path("/etc/ssl/cert.pem"),
        Path("/opt/miniconda3/envs/dev/ssl/cert.pem"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            candidate_context = ssl.create_default_context(cafile=str(candidate))
            if candidate_context.cert_store_stats()["x509_ca"] > 0:
                return candidate_context
    raise RuntimeError("No trusted CA bundle is available for HTTPS downloads")


def http_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60, context=build_ssl_context()) as response:
        return response.read()


def resolve_commit(source: SourceSpec) -> str:
    owner_repo = source.repo.removeprefix("https://github.com/").removesuffix(".git")
    url = f"https://api.github.com/repos/{owner_repo}/commits/{source.branch}"
    payload = json.loads(http_bytes(url).decode("utf-8"))
    return validate_commit(payload["sha"])


def safe_extract(bundle: tarfile.TarFile, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_resolved = destination.resolve()
    for member in bundle.getmembers():
        target = (destination / member.name).resolve()
        if target != destination_resolved and destination_resolved not in target.parents:
            raise ValueError(f"Unsafe archive member: {member.name}")
        if member.issym() or member.islnk():
            raise ValueError(f"Archive links are not accepted: {member.name}")
    bundle.extractall(destination, filter="data")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract_zip(archive: zipfile.ZipFile, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"Unsafe wheel member: {member.filename}")
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError(f"Wheel links are not accepted: {member.filename}")
    archive.extractall(destination)


@contextmanager
def temporary_converter(fetch_bytes=http_bytes):
    wheel_bytes = fetch_bytes(OPENCC_WHEEL_URL)
    actual_hash = hashlib.sha256(wheel_bytes).hexdigest()
    if actual_hash != OPENCC_WHEEL_SHA256:
        raise RuntimeError(f"OpenCC wheel hash mismatch: {actual_hash}")
    previous_modules = {
        name: module for name, module in sys.modules.items() if name == "opencc" or name.startswith("opencc.")
    }
    with tempfile.TemporaryDirectory(prefix="opencc-runtime-") as temporary:
        runtime = Path(temporary)
        wheel = runtime / "opencc.whl"
        wheel.write_bytes(wheel_bytes)
        package_root = runtime / "package"
        with zipfile.ZipFile(wheel) as archive:
            safe_extract_zip(archive, package_root)
        for name in list(sys.modules):
            if name == "opencc" or name.startswith("opencc."):
                del sys.modules[name]
        sys.path.insert(0, str(package_root))
        importlib.invalidate_caches()
        try:
            from opencc import OpenCC

            converter = OpenCC(OPENCC_CONFIG)
            yield converter.convert
        finally:
            if str(package_root) in sys.path:
                sys.path.remove(str(package_root))
            for name in list(sys.modules):
                if name == "opencc" or name.startswith("opencc."):
                    del sys.modules[name]
            sys.modules.update(previous_modules)
            importlib.invalidate_caches()


def text_line_count(value: str) -> int:
    return len(value.splitlines())


def convert_file(source: Path, destination: Path, convert) -> dict:
    upstream_bytes = source.read_bytes()
    upstream_text = upstream_bytes.decode("utf-8")
    simplified_text = convert(upstream_text)
    if text_line_count(upstream_text) != text_line_count(simplified_text):
        raise RuntimeError(f"OpenCC changed line count for {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(simplified_text, encoding="utf-8", newline="")
    simplified_bytes = destination.read_bytes()
    return {
        "path": destination.as_posix(),
        "bytes": len(simplified_bytes),
        "sha256": hashlib.sha256(simplified_bytes).hexdigest(),
        "line_count": text_line_count(simplified_text),
        "upstream_bytes": len(upstream_bytes),
        "upstream_sha256": hashlib.sha256(upstream_bytes).hexdigest(),
        "upstream_line_count": text_line_count(upstream_text),
    }


def build_manifest(
    resolved_sources: list[tuple[SourceSpec, str, list[dict]]],
    generated_at: str | None = None,
) -> dict:
    source_records = []
    for source, commit, files in resolved_sources:
        commit = validate_commit(commit)
        source_records.append(
            {
                "slug": source.slug,
                "work": source.work,
                "author": source.author,
                "repo": source.repo,
                "branch": source.branch,
                "commit": commit,
                "license": source.license_name,
                "license_basis_url": source.license_basis_url,
                "license_qualification": (
                    "Upstream organization profile; repository has no SPDX metadata"
                ),
                "files": sorted(files, key=lambda item: item["path"]),
            }
        )
    conversion = {
        "package": OPENCC_PACKAGE,
        "version": OPENCC_VERSION,
        "config": OPENCC_CONFIG,
        "wheel_sha256": OPENCC_WHEEL_SHA256,
        "license": "Apache-2.0",
    }
    canonical = json.dumps(
        {
            "conversion": conversion,
            "sources": source_records,
            "text_variant": "simplified-transcription",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema_version": 2,
        "generated_at": generated_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "text_variant": "simplified-transcription",
        "conversion": conversion,
        "sources": source_records,
        "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def download_source(source: SourceSpec, commit: str, upstream_root: Path) -> Path:
    owner_repo = source.repo.removeprefix("https://github.com/").removesuffix(".git")
    archive_url = f"https://github.com/{owner_repo}/archive/{commit}.tar.gz"
    with tempfile.TemporaryDirectory(prefix=f"{source.slug}-") as temporary:
        temporary_path = Path(temporary)
        archive_path = temporary_path / "source.tar.gz"
        archive_path.write_bytes(http_bytes(archive_url))
        extracted = temporary_path / "extracted"
        with tarfile.open(archive_path, "r:gz") as bundle:
            safe_extract(bundle, extracted)
        roots = [item for item in extracted.iterdir() if item.is_dir()]
        if len(roots) != 1:
            raise RuntimeError(f"Unexpected archive layout for {source.repo}")
        selected = sorted(
            item for item in roots[0].iterdir() if item.is_file() and (item.suffix == ".txt" or item.name == "Readme.org")
        )
        txt_count = sum(item.suffix == ".txt" for item in selected)
        if txt_count < source.minimum_txt_files:
            raise RuntimeError(
                f"{source.work} only has {txt_count} text files; expected at least {source.minimum_txt_files}"
            )
        destination = upstream_root / source.slug
        destination.mkdir(parents=True, exist_ok=False)
        for item in selected:
            shutil.copy2(item, destination / item.name)
        return destination


def convert_source(source: SourceSpec, upstream_directory: Path, destination_root: Path, convert) -> list[dict]:
    records = []
    for upstream_file in sorted(item for item in upstream_directory.iterdir() if item.is_file()):
        destination = destination_root / source.slug / upstream_file.name
        record = convert_file(upstream_file, destination, convert)
        record["path"] = destination.relative_to(destination_root.parent).as_posix()
        records.append(record)
    return records


def fetch_all(destination: Path, sources: list[SourceSpec] = SOURCES, force: bool = False) -> dict:
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        if not force:
            raise FileExistsError(f"Destination is not empty: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    backup = None
    try:
        (stage / "text").mkdir(parents=True)
        resolved = []
        with temporary_converter() as convert:
            with tempfile.TemporaryDirectory(prefix="history-upstream-") as upstream_temporary:
                upstream_root = Path(upstream_temporary)
                for source in sources:
                    commit = resolve_commit(source)
                    upstream_directory = download_source(source, commit, upstream_root)
                    files = convert_source(source, upstream_directory, stage / "text", convert)
                    resolved.append((source, commit, files))
        manifest = build_manifest(resolved)
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if destination.exists():
            if any(destination.iterdir()):
                backup = destination.with_name(f".{destination.name}-backup-{uuid.uuid4().hex}")
                destination.rename(backup)
            else:
                destination.rmdir()
        stage.rename(destination)
        if backup is not None:
            shutil.rmtree(backup)
        return manifest
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        if backup is not None and backup.exists() and not destination.exists():
            backup.rename(destination)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest = fetch_all(args.destination, force=args.force)
    summary = {
        item["slug"]: {"commit": item["commit"], "files": len(item["files"])}
        for item in manifest["sources"]
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
