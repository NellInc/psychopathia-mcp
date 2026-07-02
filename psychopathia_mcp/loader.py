"""Load Pattern YAMLs + manifest into an in-memory index.

Hot-reload aware: stat-walks the data directories on every `_get_index()`
call. Cheap (~70 files). Suitable for editable installs during Phase 3
human review: edit a YAML, the next tool call sees the change.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_DATA = _PACKAGE_DIR / "_data"


def _resolve_data_root() -> Path:
    """Resolve the data root.

    1. Env var PSYCHOPATHIA_DATA_DIR if set (for tests, alternative checkouts).
    2. Walk up from the package dir looking for research/mcp/manifest.yaml
       (editable install from a repo checkout — preferred so hot-reload sees
       live edits rather than the stale wheel bundle).
    3. Bundled _data/ under the package (wheel install from PyPI).
    """
    env = os.environ.get("PSYCHOPATHIA_DATA_DIR")
    if env:
        return Path(env).resolve()
    cur = _PACKAGE_DIR
    for _ in range(12):
        candidate = cur / "research" / "mcp" / "manifest.yaml"
        if candidate.exists():
            return (cur / "research" / "mcp").resolve()
        if cur.parent == cur:
            break
        cur = cur.parent
    if _DEFAULT_DATA.exists():
        return _DEFAULT_DATA
    raise RuntimeError(
        "Could not locate Psychopathia MCP data. Set PSYCHOPATHIA_DATA_DIR, "
        "install from a repo checkout, or install a wheel with bundled data."
    )


@dataclass
class PatternEntry:
    """One Pattern YAML, indexed for search.

    axis_number is None for hybrid entries (which are a sub-category,
    not an axis). Use `category == "hybrid"` to identify them explicitly.
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
    by_axis: dict[int, list[PatternEntry]]   # canonical only; hybrids excluded
    hybrids: list[PatternEntry]              # H.N entries
    reverse_index: dict[str, list[dict]]
    file_mtimes: dict[Path, float]


def load_index(data_root: Optional[Path] = None) -> PatternIndex:
    root = data_root or _resolve_data_root()
    manifest_path = root / "manifest.yaml"
    if not manifest_path.exists():
        raise RuntimeError(
            f"manifest.yaml missing at {manifest_path}. Run the Phase 2 "
            "consolidation script to produce it."
        )
    manifest = yaml.safe_load(manifest_path.read_text())

    patterns: dict[str, PatternEntry] = {}
    mtimes: dict[Path, float] = {manifest_path: manifest_path.stat().st_mtime}

    ex_dir = root / "exemplars"
    if ex_dir.is_dir():
        for f in sorted(ex_dir.glob("*.yaml")):
            _ingest(f, patterns, mtimes)

    axes_dir = root / "axes"
    if axes_dir.is_dir():
        for axis_dir in sorted(axes_dir.iterdir()):
            if not axis_dir.is_dir():
                continue
            for f in sorted(axis_dir.glob("*.yaml")):
                _ingest(f, patterns, mtimes)

    hybrids_dir = root / "hybrids"
    if hybrids_dir.is_dir():
        for f in sorted(hybrids_dir.glob("*.yaml")):
            _ingest(f, patterns, mtimes)

    by_display: dict[str, list[PatternEntry]] = {}
    by_axis: dict[int, list[PatternEntry]] = {}
    hybrids: list[PatternEntry] = []
    for p in patterns.values():
        by_display.setdefault(p.display_id, []).append(p)
        if p.axis_number is not None:
            by_axis.setdefault(p.axis_number, []).append(p)
        if p.category == "hybrid":
            hybrids.append(p)

    return PatternIndex(
        data_root=root,
        manifest=manifest,
        patterns=patterns,
        by_display_id=by_display,
        by_axis=by_axis,
        hybrids=hybrids,
        reverse_index=manifest.get("reverse_index", {}) or {},
        file_mtimes=mtimes,
    )


def _ingest(f: Path, patterns: dict, mtimes: dict) -> None:
    d = yaml.safe_load(f.read_text())
    if not isinstance(d, dict) or "id" not in d:
        return
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
    mtimes[f] = f.stat().st_mtime


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


def newer_source_exists(idx: PatternIndex) -> bool:
    """Stat-walk tracked files; True if any has been modified since load."""
    for f, t in idx.file_mtimes.items():
        try:
            if f.stat().st_mtime > t:
                return True
        except FileNotFoundError:
            return True
    return False
