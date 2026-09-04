#!/usr/bin/env bash
# Prepare a deterministic public-repository candidate. This script has no
# network, Git commit, push, upload, registry, or deployment operation.
set -euo pipefail

SERVER_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MONO_ROOT="$(cd "$SERVER_DIR/../../.." && pwd)"
OUTPUT="$MONO_ROOT/dist/psychopathia-mcp-public-candidate"

if [[ "${1:-}" == "--output" ]]; then
  [[ $# -eq 2 ]] || { echo "Usage: $0 [--output DIRECTORY]" >&2; exit 2; }
  OUTPUT="$2"
elif [[ $# -eq 1 ]]; then
  OUTPUT="$1"
elif [[ $# -ne 0 ]]; then
  echo "Usage: $0 [--output DIRECTORY]" >&2; exit 2
fi
[[ "$OUTPUT" = /* ]] || OUTPUT="$MONO_ROOT/$OUTPUT"
OUTPUT="$(python3 - "$OUTPUT" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PY
)"

case "$OUTPUT" in
  /|"$HOME"|"$MONO_ROOT"|"$SERVER_DIR"|"") echo "Unsafe output directory: $OUTPUT" >&2; exit 2 ;;
esac
case "$OUTPUT/" in "$SERVER_DIR/"*) echo "Output must be outside the MCP source tree: $OUTPUT" >&2; exit 2 ;; esac
case "$MONO_ROOT/" in "$OUTPUT/"*) echo "Output may not contain the repository: $OUTPUT" >&2; exit 2 ;; esac
[[ ! -L "$OUTPUT" ]] || { echo "Output may not be a symlink: $OUTPUT" >&2; exit 2; }

RECEIPT="$SERVER_DIR/dist/MCP_CANDIDATE_RECEIPT.json"
[[ -f "$RECEIPT" ]] || { echo "Verify wheel and sdist before preparing the public candidate." >&2; exit 2; }
python3 "$SERVER_DIR/scripts/sync_data_for_wheel.py" --check
python3 "$MONO_ROOT/scripts/sync_mcp_metadata.py" --check

if [[ -e "$OUTPUT" ]]; then
  [[ -f "$OUTPUT/PUBLIC_SOURCE_CANDIDATE.json" ]] || {
    echo "Refusing to replace an unmarked directory: $OUTPUT" >&2; exit 2;
  }
  python3 - "$OUTPUT/PUBLIC_SOURCE_CANDIDATE.json" <<'PY'
from pathlib import Path
import json, sys
value = json.loads(Path(sys.argv[1]).read_text())
assert value.get("schema_version") == 1
assert value.get("publication") == "NOT_AUTHORIZED"
PY
fi

mkdir -p "$(dirname "$OUTPUT")"
STAGING="$(mktemp -d "$(dirname "$OUTPUT")/.psychopathia-mcp-public.XXXXXX")"
BACKUP=""
cleanup() {
  [[ -z "$BACKUP" || ! -e "$BACKUP" ]] || mv "$BACKUP" "$OUTPUT"
  [[ ! -e "$STAGING" ]] || rm -rf "$STAGING"
}
trap cleanup EXIT

rsync -a \
  --exclude '.venv/' --exclude 'dist/' --exclude 'build/' --exclude '*.egg-info/' \
  --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude '.benchmarks/' \
  --exclude 'node_modules/' --exclude 'mcpb/server/' --exclude '*.mcpb' \
  --exclude '*.pyc' --exclude '.git/' --exclude '.DS_Store' \
  "$SERVER_DIR/" "$STAGING/"
[[ -f "$MONO_ROOT/glama.json" ]] && cp "$MONO_ROOT/glama.json" "$STAGING/glama.json"

cat > "$STAGING/.gitignore" <<'EOF'
dist/
build/
*.egg-info/
__pycache__/
*.pyc
.pytest_cache/
.benchmarks/
.venv/
node_modules/
mcpb/server/lib/
*.mcpb
EOF

python3 - "$STAGING" "$RECEIPT" <<'PY'
from pathlib import Path
from hashlib import sha256
import json, sys

root, receipt_path = Path(sys.argv[1]), Path(sys.argv[2])
receipt = json.loads(receipt_path.read_text())
excluded = {"PUBLIC_SOURCE_CANDIDATE.json", "PUBLIC_SOURCE_SHA256SUMS"}
records = []
for path in sorted(root.rglob("*")):
    if path.is_symlink():
        raise SystemExit(f"symlinks are forbidden in the public candidate: {path}")
    if not path.is_file() or path.name in excluded:
        continue
    relative = path.relative_to(root).as_posix()
    records.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path.read_bytes()).hexdigest()})
digest = sha256()
for item in records:
    digest.update(item["path"].encode())
    digest.update(b"\0")
    digest.update(item["sha256"].encode())
    digest.update(b"\n")
candidate = receipt["candidate"]
manifest = {
    "schema_version": 1,
    "source_commit": candidate["source_commit"],
    "source_tree_clean": candidate["source_tree_clean"],
    "package_source_sha256": candidate["package_source_sha256"],
    "version": candidate["version"],
    "payload_files": len(records),
    "payload_bytes": sum(item["bytes"] for item in records),
    "payload_sha256": digest.hexdigest(),
    "publication": "NOT_AUTHORIZED",
    "hold": "Prepared candidate only. No commit, push, upload, registry mutation, or deployment was performed.",
}
manifest_path = root / "PUBLIC_SOURCE_CANDIDATE.json"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
checksummed = records + [{
    "path": manifest_path.name,
    "sha256": sha256(manifest_path.read_bytes()).hexdigest(),
}]
(root / "PUBLIC_SOURCE_SHA256SUMS").write_text(
    "".join(f'{item["sha256"]}  {item["path"]}\n' for item in sorted(checksummed, key=lambda row: row["path"]))
)
PY

python3 "$MONO_ROOT/scripts/verify_mcp_public_candidate.py" "$STAGING" --receipt "$RECEIPT"

if [[ -e "$OUTPUT" ]]; then
  BACKUP="${OUTPUT}.previous.$$"
  mv "$OUTPUT" "$BACKUP"
fi
mv "$STAGING" "$OUTPUT"
STAGING=""
[[ -z "$BACKUP" ]] || { rm -rf "$BACKUP"; BACKUP=""; }
trap - EXIT

echo "Prepared held public-repository candidate at $OUTPUT"
echo "No clone, commit, push, upload, publication, registry mutation, or deployment was performed."
