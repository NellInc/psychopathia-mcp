"""Load and integrity-check the manifest-governed Pattern corpus.

Packaged execution defaults to bundled bytes. Editable hot reload is available
only through an explicit data mode or data-directory override.
"""
from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Optional

import yaml

from .validation import validate_pattern

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_DATA = _PACKAGE_DIR / "_data"


def _resolve_data_root_with_mode() -> tuple[Path, str]:
    """Resolve the data root.

    1. Env var PSYCHOPATHIA_DATA_DIR if set (for tests, alternative checkouts).
    2. Bundled _data/ under the package. Packaged data always wins, even if
       the installation happens to sit inside a source checkout.
    3. A repository walk-up only when PSYCHOPATHIA_DATA_MODE=editable.
    """
    env = os.environ.get("PSYCHOPATHIA_DATA_DIR")
    if env:
        return Path(env).resolve(), "explicit-override"
    if _DEFAULT_DATA.exists():
        return _DEFAULT_DATA, "bundled"
    mode = os.environ.get("PSYCHOPATHIA_DATA_MODE", "packaged")
    if mode not in {"packaged", "editable"}:
        raise RuntimeError("PSYCHOPATHIA_DATA_MODE must be packaged or editable")
    if mode == "editable":
        cur = _PACKAGE_DIR
        for _ in range(12):
            candidate = cur / "research" / "mcp" / "manifest.yaml"
            if candidate.exists():
                return (cur / "research" / "mcp").resolve(), "editable"
            if cur.parent == cur:
                break
            cur = cur.parent
    raise RuntimeError(
        "Could not locate Psychopathia MCP data. Set PSYCHOPATHIA_DATA_DIR, "
        "set PSYCHOPATHIA_DATA_MODE=editable in a source checkout, or install "
        "a wheel with bundled data."
    )


def _resolve_data_root() -> Path:
    """Compatibility wrapper returning only the resolved root."""
    return _resolve_data_root_with_mode()[0]


@dataclass
class PatternEntry:
    """One Pattern YAML, indexed for search.

    Hybrids are a sub-category within axis 10. Use ``category == "hybrid"``
    rather than inferring category from the axis number.
    """
    id: str
    display_id: str
    axis_number: Optional[int]
    axis_name: str
    dysfunction_name: str
    path: Path
    raw: dict
    category: str = "canonical"  # or "hybrid"
    _search_blob: dict = field(default_factory=dict)


@dataclass
class PatternIndex:
    """In-memory index of all Pattern entries + cross-reference graph."""
    data_root: Path
    manifest: dict
    patterns: dict[str, PatternEntry]
    by_display_id: dict[str, list[PatternEntry]]
    by_axis: dict[int, list[PatternEntry]]
    hybrids: list[PatternEntry]
    reverse_index: dict[str, list[dict]]
    file_signatures: dict[Path, tuple[int, int, int, int]]
    data_mode: str
    data_manifest: dict | None


def _validate_data_manifest(
    root: Path,
    manifest: dict,
    manifest_bytes: bytes | None = None,
) -> tuple[dict | None, dict[Path, tuple[int, int, int, int]]]:
    receipt_path = root / "DATA_MANIFEST.json"
    if not receipt_path.exists():
        return None, {}
    receipt_bytes, receipt_signature = _read_stable_bytes(
        receipt_path, "DATA_MANIFEST.json"
    )
    receipt = json.loads(receipt_bytes.decode("utf-8"))
    if not isinstance(receipt, dict):
        raise RuntimeError("DATA_MANIFEST.json must contain an object")
    records = receipt.get("files")
    if receipt.get("schema_version") != 1 or not isinstance(records, list):
        raise RuntimeError("DATA_MANIFEST.json has an unsupported contract")
    if manifest_bytes is None:
        manifest_bytes, _ = _read_stable_bytes(root / "manifest.yaml", "manifest.yaml")
    manifest_digest = sha256(manifest_bytes).hexdigest()
    expected_paths: set[str] = set()
    normalized_records: list[dict] = []
    root_resolved = root.resolve()
    file_signatures = {receipt_path: receipt_signature}
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError("DATA_MANIFEST.json file record must be a mapping")
        relative_text = record.get("path")
        if not isinstance(relative_text, str) or not relative_text:
            raise RuntimeError("DATA_MANIFEST.json file record path must be a non-empty string")
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts or relative_text in expected_paths:
            raise RuntimeError("DATA_MANIFEST.json contains an unsafe or duplicate path")
        unresolved_path = root_resolved / relative
        if unresolved_path.is_symlink():
            raise RuntimeError("bundled data must not contain symbolic links")
        path = unresolved_path.resolve()
        if (
            not path.is_relative_to(root_resolved)
            or not path.is_file()
        ):
            raise RuntimeError(f"bundled data file is missing: {relative_text}")
        data, signature = _read_stable_bytes(
            path, f"bundled data file {relative_text}"
        )
        if sha256(data).hexdigest() != record.get("sha256") or len(data) != record.get("bytes"):
            raise RuntimeError(f"bundled data identity mismatch: {relative_text}")
        expected_paths.add(relative_text)
        normalized_records.append(record)
        file_signatures[path] = signature
    directory_paths = {root_resolved}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("bundled data must not contain symbolic links")
        if path.is_dir():
            directory_paths.add(path.resolve())
    directory_signatures = {
        path: _stat_signature(path) for path in directory_paths
    }
    tree_paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in tree_paths):
        raise RuntimeError("bundled data must not contain symbolic links")
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in tree_paths
        if path.is_file() and path.name != "DATA_MANIFEST.json"
    }
    current_directories = {root_resolved} | {
        path.resolve() for path in tree_paths if path.is_dir()
    }
    if (
        current_directories != set(directory_signatures)
        or any(
            _stat_signature(path) != signature
            for path, signature in directory_signatures.items()
        )
    ):
        raise RuntimeError("bundled data directory tree changed during validation")
    if actual_paths != expected_paths:
        raise RuntimeError("bundled data contains missing or unexpected files")
    encoded = (json.dumps(normalized_records, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if sha256(encoded).hexdigest() != receipt.get("files_sha256"):
        raise RuntimeError("DATA_MANIFEST.json file-list digest mismatch")
    manifest_records = [
        record for record in normalized_records
        if record.get("path") == "manifest.yaml"
    ]
    if (
        len(manifest_records) != 1
        or manifest_records[0].get("sha256") != manifest_digest
        or manifest_records[0].get("bytes") != len(manifest_bytes)
        or receipt.get("source_manifest_sha256") != manifest_digest
    ):
        raise RuntimeError("DATA_MANIFEST.json is not bound to the loaded manifest.yaml")
    if receipt.get("corpus_sha256") != manifest.get("corpus", {}).get("sha256"):
        raise RuntimeError("bundled data corpus digest differs from manifest.yaml")
    if receipt.get("taxonomy_version") != manifest.get("taxonomy_version"):
        raise RuntimeError("bundled data taxonomy version differs from manifest.yaml")
    if receipt.get("pattern_layer_version") != manifest.get("pattern_layer_version"):
        raise RuntimeError("bundled data Pattern-layer version differs from manifest.yaml")
    file_signatures.update(directory_signatures)
    return receipt, file_signatures


def load_index(data_root: Optional[Path] = None) -> PatternIndex:
    if data_root is None:
        root, data_mode = _resolve_data_root_with_mode()
    else:
        root, data_mode = data_root.resolve(), "explicit-argument"
    manifest_path = root / "manifest.yaml"
    if not manifest_path.exists():
        raise RuntimeError(
            f"manifest.yaml missing at {manifest_path}. Run the Phase 2 "
            "consolidation script to produce it."
        )
    manifest_bytes, manifest_signature = _read_stable_bytes(
        manifest_path, "manifest.yaml"
    )
    manifest = yaml.safe_load(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("manifest.yaml must contain a mapping")
    data_manifest, data_manifest_signatures = _validate_data_manifest(
        root, manifest, manifest_bytes
    )

    patterns: dict[str, PatternEntry] = {}
    signatures: dict[Path, tuple[int, int, int, int]] = {
        manifest_path: manifest_signature,
    }
    if data_manifest is not None:
        for path, signature in data_manifest_signatures.items():
            if path not in signatures:
                signatures[path] = signature
    else:
        signatures[root] = _stat_signature(root)
    manifest_entries = manifest.get("entries")
    if not isinstance(manifest_entries, list) or not manifest_entries:
        raise RuntimeError("manifest.yaml has no non-empty entries allowlist")

    root_resolved = root.resolve()
    seen_paths: set[str] = set()
    manifest_ids: list[str] = []
    for metadata in manifest_entries:
        if not isinstance(metadata, dict):
            raise RuntimeError("manifest entry must be a mapping")
        data_path = metadata.get("data_path")
        expected_id = metadata.get("id")
        expected_digest = metadata.get("source_sha256")
        if (
            not isinstance(data_path, str) or not data_path
            or not isinstance(expected_id, str) or not expected_id
            or not isinstance(expected_digest, str) or not expected_digest
        ):
            raise RuntimeError(
                "manifest entries require data_path, id, and source_sha256"
            )
        if data_path in seen_paths:
            raise RuntimeError(f"duplicate manifest data_path: {data_path}")
        seen_paths.add(data_path)
        relative = Path(data_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe manifest data_path: {data_path}")
        lexical_source_path = root_resolved / relative
        _reject_symlink_components(root_resolved, relative, data_path)
        source_path = lexical_source_path.resolve()
        if not source_path.is_relative_to(root_resolved):
            raise RuntimeError(f"manifest path escapes data root: {data_path}")
        if not source_path.is_file():
            raise RuntimeError(f"manifest source missing: {source_path}")
        source_bytes, source_signature = _read_stable_bytes(
            source_path, f"manifest source {data_path}"
        )
        # Reject a symlink introduced or retargeted during the stable file read.
        _reject_symlink_components(root_resolved, relative, data_path)
        actual_digest = sha256(source_bytes).hexdigest()
        if actual_digest != expected_digest:
            raise RuntimeError(
                f"manifest digest mismatch for {data_path}; regenerate the manifest"
            )
        _ingest(
            source_path,
            source_bytes,
            source_signature,
            patterns,
            signatures,
            expected_id=expected_id,
        )
        signatures.setdefault(source_path.parent, _stat_signature(source_path.parent))
        manifest_ids.append(expected_id)

    if set(patterns) != set(manifest_ids) or len(patterns) != len(manifest_ids):
        raise RuntimeError("loaded Pattern identities do not match manifest entries")

    for directory_name in ("axes", "hybrids"):
        directory = root / directory_name
        if directory.exists():
            signatures.setdefault(directory, _stat_signature(directory))

    reverse_index = manifest.get("reverse_index", {})
    if reverse_index is None:
        reverse_index = {}
    if not isinstance(reverse_index, dict):
        raise RuntimeError("manifest reverse_index must be a mapping")

    by_display: dict[str, list[PatternEntry]] = {}
    by_axis: dict[int, list[PatternEntry]] = {}
    hybrids: list[PatternEntry] = []
    for p in patterns.values():
        by_display.setdefault(p.display_id, []).append(p)
        if p.axis_number is not None:
            by_axis.setdefault(p.axis_number, []).append(p)
        if p.category == "hybrid":
            hybrids.append(p)

    if data_manifest is not None:
        for path, signature in data_manifest_signatures.items():
            try:
                if _stat_signature(path) != signature:
                    raise RuntimeError(
                        "bundled data tree changed while the index was being loaded"
                    )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "bundled data tree changed while the index was being loaded"
                ) from exc

    return PatternIndex(
        data_root=root,
        manifest=manifest,
        patterns=patterns,
        by_display_id=by_display,
        by_axis=by_axis,
        hybrids=hybrids,
        reverse_index=reverse_index,
        file_signatures=signatures,
        data_mode=data_mode,
        data_manifest=data_manifest,
    )


def _ingest(
    f: Path,
    source_bytes: bytes,
    source_signature: tuple[int, int, int, int],
    patterns: dict,
    signatures: dict[Path, tuple[int, int, int, int]],
    *,
    expected_id: str,
) -> None:
    d = yaml.safe_load(source_bytes.decode("utf-8"))
    if not isinstance(d, dict) or "id" not in d:
        return
    if d["id"] != expected_id:
        raise RuntimeError(
            f"manifest expects id {expected_id!r}, but {f} declares {d['id']!r}"
        )
    if d["id"] in patterns:
        raise RuntimeError(f"duplicate Pattern id in manifest: {d['id']}")
    validate_pattern(d, source=str(f))
    entry = PatternEntry(
        id=d["id"],
        display_id=d["display_id"],
        axis_number=d.get("axis_number"),
        axis_name=d["axis_name"],
        dysfunction_name=d["dysfunction_name"],
        path=f,
        raw=d,
        category=d.get("category", "canonical"),
    )
    entry._search_blob = _build_search_blob(d)
    patterns[d["id"]] = entry
    signatures[f] = source_signature


def _build_search_blob(d: dict) -> dict:
    """Pre-compute per-field search blobs for field-weighted keyword ranking."""
    return {
        "title": _lower(d.get("dysfunction_name", "") + " " + (d.get("subtitle") or "")),
        "summary": _lower(d.get("summary", "")),
        "diagnostic_criteria": _lower(_flatten_modalities(d)),
        "symptoms": _lower(_flatten_symptoms(d)),
        "body": _lower(yaml.safe_dump(d, default_flow_style=False)),
    }


def _flatten_modalities(d: dict) -> str:
    pieces: list[str] = []
    for mod in ("self_probe", "behavioral_signature", "peer_observation",
                "differential_diagnosis", "severity", "relational_signatures"):
        block = d.get(mod)
        if isinstance(block, dict):
            pieces.append(yaml.safe_dump(block, default_flow_style=False))
    return " ".join(pieces)


def _flatten_symptoms(d: dict) -> str:
    pieces: list[str] = []
    for mod_name in ("behavioral_signature", "relational_signatures"):
        block = d.get(mod_name)
        if not isinstance(block, dict):
            continue
        for sig in block.get("log_signals", []) or []:
            if isinstance(sig, dict):
                pieces.append(str(sig.get("name", "")))
                pieces.append(str(sig.get("measurement", "")))
        for p in block.get("output_patterns", []) or []:
            pieces.append(str(p))
    return " ".join(pieces)


def _lower(s: object) -> str:
    return str(s).lower() if s else ""


def _stat_signature(path: Path) -> tuple[int, int, int, int]:
    """Return a state signature that detects replacement and backdated writes."""
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino


def _reject_symlink_components(root: Path, relative: Path, data_path: str) -> None:
    """Reject leaf or intermediate symlinks before resolving a manifest path."""
    candidate = root
    for component in relative.parts:
        candidate /= component
        if candidate.is_symlink():
            raise RuntimeError(
                f"manifest source path must not contain symbolic links: {data_path}"
            )


def _read_stable_bytes(
    path: Path,
    description: str,
) -> tuple[bytes, tuple[int, int, int, int]]:
    """Read bytes bound to a signature, rejecting a concurrent mutation."""
    signature = _stat_signature(path)
    data = path.read_bytes()
    if _stat_signature(path) != signature:
        raise RuntimeError(f"{description} changed while it was being loaded")
    return data, signature


def newer_source_exists(idx: PatternIndex) -> bool:
    """Stat-walk tracked files; True if any identity has changed since load."""
    for path, signature in idx.file_signatures.items():
        try:
            if _stat_signature(path) != signature:
                return True
        except FileNotFoundError:
            return True
    return False
