#!/usr/bin/env python3
"""Build and verify the exact manifest-governed MCP package data bundle."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import shutil
import struct
import tempfile
from pathlib import Path

import yaml

SERVER_DIR = Path(__file__).resolve().parent.parent
PACKAGE_DIR = SERVER_DIR / "psychopathia_mcp"
DATA_DIR = PACKAGE_DIR / "_data"
SOURCE_ROOT = SERVER_DIR.parent
TOP_LEVEL_FILES = (
    "manifest.yaml",
    "embeddings.npy",
    "embedding_ids.txt",
    "embeddings_metadata.yaml",
    "schema.yaml",
)
MAX_NPY_HEADER_BYTES = 64 * 1024


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_regular_file_within(root: Path, path: Path) -> bool:
    """Return whether path is a regular, non-symlink file beneath root."""
    try:
        relative = path.relative_to(root)
        root_resolved = root.resolve(strict=True)
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return False
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return False
    return resolved.is_relative_to(root_resolved) and resolved.is_file()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def corpus_digest(entries: list[dict]) -> str:
    value = hashlib.sha256()
    for entry in entries:
        value.update(entry["data_path"].encode("utf-8"))
        value.update(b"\0")
        value.update(entry["source_sha256"].encode("ascii"))
        value.update(b"\n")
    return value.hexdigest()


def npy_header(path: Path) -> tuple[str, tuple[int, ...], bool]:
    """Read a NumPy v1 through v3 header without importing NumPy."""
    with path.open("rb") as stream:
        if stream.read(6) != b"\x93NUMPY":
            raise ValueError("embeddings.npy has no NumPy magic header")
        major, minor = stream.read(2)
        if (major, minor) == (1, 0):
            header_length = struct.unpack("<H", stream.read(2))[0]
            encoding = "latin1"
        elif major in {2, 3}:
            header_length = struct.unpack("<I", stream.read(4))[0]
            encoding = "utf-8" if major == 3 else "latin1"
        else:
            raise ValueError(f"unsupported embeddings.npy format {major}.{minor}")
        if header_length > MAX_NPY_HEADER_BYTES:
            raise ValueError("embeddings.npy header exceeds the size limit")
        header_bytes = stream.read(header_length)
        if len(header_bytes) != header_length:
            raise ValueError("embeddings.npy header is truncated")
        header = ast.literal_eval(header_bytes.decode(encoding).strip())
        payload_offset = stream.tell()
    if not isinstance(header, dict) or set(header) != {"descr", "shape", "fortran_order"}:
        raise ValueError("embeddings.npy header mapping is invalid")
    descr = header["descr"]
    shape = header["shape"]
    fortran = header["fortran_order"]
    if (
        not isinstance(descr, str)
        or not isinstance(shape, tuple)
        or not shape
        or not all(isinstance(size, int) and not isinstance(size, bool) and size >= 0 for size in shape)
        or not isinstance(fortran, bool)
    ):
        raise ValueError("embeddings.npy header values are invalid")
    if descr in {"<f4", "=f4", "|f4"}:
        expected_bytes = payload_offset + math.prod(shape) * 4
        if path.stat().st_size != expected_bytes:
            raise ValueError("embeddings.npy payload size does not match its header")
    return descr, shape, fortran


def validate_source(source_root: Path = SOURCE_ROOT) -> tuple[dict, list[str]]:
    for name in TOP_LEVEL_FILES:
        if not is_regular_file_within(source_root, source_root / name):
            raise ValueError(f"required package-data source is missing: {name}")
    manifest = yaml.safe_load((source_root / "manifest.yaml").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a mapping")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or len(entries) != 79:
        raise ValueError("manifest must contain exactly 79 entries")
    if not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("manifest entries must be mappings")
    paths = [entry.get("data_path") for entry in entries]
    ids = [entry.get("id") for entry in entries]
    if not all(isinstance(item, str) and item for item in paths + ids):
        raise ValueError("manifest paths and IDs must be non-empty strings")
    if len(paths) != len(set(paths)) or len(ids) != len(set(ids)):
        raise ValueError("manifest contains duplicate paths or IDs")
    expected_yaml = set(paths)
    actual_yaml_paths = [
        path
        for root in (source_root / "axes", source_root / "hybrids")
        for path in root.rglob("*.yaml")
    ]
    for path in actual_yaml_paths:
        if not is_regular_file_within(source_root, path):
            raise ValueError(
                "package-data source must be a regular file within the source root: "
                f"{path}"
            )
    actual_yaml = {
        path.relative_to(source_root).as_posix()
        for path in actual_yaml_paths
    }
    if actual_yaml != expected_yaml:
        raise ValueError(
            "manifest/YAML allowlist mismatch: "
            f"missing={sorted(expected_yaml - actual_yaml)}, unexpected={sorted(actual_yaml - expected_yaml)}"
        )
    for entry in entries:
        relative = Path(entry["data_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe manifest data_path: {relative}")
        source = source_root / relative
        if not is_regular_file_within(source_root, source):
            raise ValueError(
                "package-data source must be a regular file within the source root: "
                f"{relative}"
            )
        if digest(source) != entry.get("source_sha256"):
            raise ValueError(f"manifest identity drift for {relative}")
    calculated_corpus = corpus_digest(entries)
    if manifest.get("corpus", {}).get("sha256") != calculated_corpus:
        raise ValueError("manifest corpus digest does not match its ordered entries")

    id_path = source_root / "embedding_ids.txt"
    embedding_ids = [line for line in id_path.read_text(encoding="utf-8").splitlines() if line]
    if embedding_ids != ids:
        raise ValueError("embedding ID order differs from manifest entry order")
    metadata = yaml.safe_load((source_root / "embeddings_metadata.yaml").read_text())
    if not isinstance(metadata, dict):
        raise ValueError("embedding metadata must be a mapping")
    if metadata.get("embeddings_sha256") != digest(source_root / "embeddings.npy"):
        raise ValueError("embedding matrix digest drifted")
    if metadata.get("embedding_ids_sha256") != digest(id_path):
        raise ValueError("embedding ID digest drifted")
    if metadata.get("corpus_sha256") != calculated_corpus:
        raise ValueError("embedding metadata corpus digest drifted")
    if metadata.get("count") != 79 or metadata.get("dtype") != "float32" or metadata.get("normalized") is not True:
        raise ValueError("embedding metadata shape or representation is invalid")
    dtype, shape, fortran = npy_header(source_root / "embeddings.npy")
    if dtype not in {"<f4", "=f4", "|f4"} or shape != (79, metadata.get("dim")) or fortran:
        raise ValueError(f"embeddings.npy header is invalid: dtype={dtype}, shape={shape}, fortran={fortran}")
    return manifest, paths


def build_bundle(destination: Path) -> dict:
    _, pattern_paths = validate_source()
    destination.mkdir(parents=True, exist_ok=False)
    roles: dict[str, str] = {
        "manifest.yaml": "corpus-manifest",
        "embeddings.npy": "embedding-matrix",
        "embedding_ids.txt": "embedding-identities",
        "embeddings_metadata.yaml": "embedding-metadata",
        "schema.yaml": "human-readable-schema",
    }
    expected = list(TOP_LEVEL_FILES) + pattern_paths
    for relative_text in sorted(expected):
        relative = Path(relative_text)
        source = SOURCE_ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    # Revalidate the private copy. This closes the validation/copy race and
    # ensures an interrupted or concurrently-mutated source cannot yield a
    # bundle that reports PASS but fails at runtime.
    validated_manifest, validated_pattern_paths = validate_source(destination)
    validated_expected = list(TOP_LEVEL_FILES) + validated_pattern_paths
    if set(validated_expected) != set(expected):
        raise ValueError("package-data source changed during bundle creation")
    file_records = []
    for relative_text in sorted(validated_expected):
        relative = Path(relative_text)
        target = destination / relative
        file_records.append(
            {
                "path": relative.as_posix(),
                "sha256": digest(target),
                "bytes": target.stat().st_size,
                "role": roles.get(relative.as_posix(), "pattern"),
            }
        )
    manifest_digest = next(
        record["sha256"]
        for record in file_records
        if record["path"] == "manifest.yaml"
    )
    payload = {
        "schema_version": 1,
        "corpus_sha256": validated_manifest["corpus"]["sha256"],
        "taxonomy_version": validated_manifest["taxonomy_version"],
        "pattern_layer_version": validated_manifest["pattern_layer_version"],
        "source_manifest_sha256": manifest_digest,
        "files_sha256": hashlib.sha256(canonical_json(file_records)).hexdigest(),
        "files": file_records,
    }
    (destination / "DATA_MANIFEST.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def trees_equal(left: Path, right: Path) -> bool:
    if left.is_symlink() or right.is_symlink() or not left.is_dir() or not right.is_dir():
        return False
    left_entries = list(left.rglob("*"))
    right_entries = list(right.rglob("*"))
    if any(path.is_symlink() for path in left_entries + right_entries):
        return False
    left_files = sorted(path.relative_to(left) for path in left_entries if path.is_file())
    right_files = sorted(path.relative_to(right) for path in right_entries if path.is_file())
    return left_files == right_files and all((left / rel).read_bytes() == (right / rel).read_bytes() for rel in left_files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pm-mcp-data-", dir=PACKAGE_DIR) as temporary:
        candidate = Path(temporary) / "_data"
        payload = build_bundle(candidate)
        if args.check:
            if not trees_equal(DATA_DIR, candidate):
                raise SystemExit("MCP package-data bundle FAIL: _data is absent or stale")
        else:
            old = PACKAGE_DIR / "_data.previous"
            if old.exists():
                shutil.rmtree(old)
            if DATA_DIR.exists():
                DATA_DIR.rename(old)
            candidate.rename(DATA_DIR)
            if old.exists():
                shutil.rmtree(old)
    print(
        "MCP package-data bundle PASS: "
        f"{len(payload['files'])} source files, corpus {payload['corpus_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
