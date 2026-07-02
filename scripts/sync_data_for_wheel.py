#!/usr/bin/env python3
"""Populate psychopathia_mcp/_data/ from the repo's research/mcp/ layout.

Run before `python -m build` so the wheel ships with Pattern YAMLs, the
manifest, and pre-computed embeddings. Without this, a pip-installed
wheel will fail at startup because the loader can't find the data.

Resolution order in loader._resolve_data_root():
  1. $PSYCHOPATHIA_DATA_DIR
  2. <package>/_data/            <- what this script populates
  3. walk-up looking for research/mcp/manifest.yaml  (editable install)

Keep _data/ out of git (see .gitignore). It is a build artifact only.
"""
from __future__ import annotations

import shutil
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
PACKAGE_DIR = SERVER_DIR / "psychopathia_mcp"
DATA_DIR = PACKAGE_DIR / "_data"
SOURCE_ROOT = SERVER_DIR.parent  # research/mcp/

TOP_LEVEL_FILES = [
    "manifest.yaml",
    "embeddings.npy",
    "embedding_ids.txt",
    "embeddings_metadata.yaml",
]
YAML_DIRS = [
    "exemplars",
    "axes",
    "hybrids",
]


def _copy_yamls_only(src: Path, dst: Path) -> int:
    """Copy every *.yaml under src to dst, preserving subdirectories."""
    count = 0
    for f in src.rglob("*.yaml"):
        rel = f.relative_to(src)
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out)
        count += 1
    return count


def main() -> None:
    if not (SOURCE_ROOT / "manifest.yaml").exists():
        raise SystemExit(
            f"manifest.yaml not found at {SOURCE_ROOT}. "
            "Run this from a Psychopathia checkout."
        )

    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir()

    print(f"Populating {DATA_DIR.relative_to(SERVER_DIR)}/ from "
          f"{SOURCE_ROOT.relative_to(SERVER_DIR.parent.parent)}/\n")

    for name in TOP_LEVEL_FILES:
        src = SOURCE_ROOT / name
        if not src.exists():
            print(f"  skip (missing): {name}")
            continue
        shutil.copy2(src, DATA_DIR / name)
        size_kb = src.stat().st_size / 1024
        print(f"  copied: {name:<32} ({size_kb:>6.1f} KB)")

    for name in YAML_DIRS:
        src = SOURCE_ROOT / name
        if not src.is_dir():
            print(f"  skip (missing): {name}/")
            continue
        dst = DATA_DIR / name
        count = _copy_yamls_only(src, dst)
        print(f"  copied: {name + '/':<32} ({count:>3} yaml files)")

    total_size = sum(f.stat().st_size for f in DATA_DIR.rglob("*") if f.is_file())
    total_files = sum(1 for f in DATA_DIR.rglob("*") if f.is_file())
    print(f"\nBundle: {total_files} files, {total_size / 1024:.1f} KB total.")


if __name__ == "__main__":
    main()
