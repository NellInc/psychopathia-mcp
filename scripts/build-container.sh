#!/usr/bin/env bash
# Build a local, publication-held container from the accepted wheel.
set -euo pipefail

SERVER_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ROOT_DIR="$(cd "$SERVER_DIR/../../.." && pwd)"
PYTHON_IMAGE="${PYTHON_IMAGE:-python:3.12-alpine@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df}"
VERSION="$(python3 -c 'import pathlib,tomllib; print(tomllib.loads(pathlib.Path("'"$SERVER_DIR"'/pyproject.toml").read_text())["project"]["version"])')"
IMAGE="${1:-psychopathia-mcp:${VERSION}-candidate}"
WHEEL="${2:-$SERVER_DIR/dist/psychopathia_mcp-${VERSION}-py3-none-any.whl}"
RECEIPT="$SERVER_DIR/dist/MCP_CANDIDATE_RECEIPT.json"

[[ "$PYTHON_IMAGE" == *@sha256:* ]] || { echo "PYTHON_IMAGE must be pinned by digest." >&2; exit 2; }
[[ -f "$WHEEL" && -f "$RECEIPT" ]] || { echo "Verify wheel and sdist before building the container." >&2; exit 2; }

read -r WHEEL_SHA SOURCE_SHA SOURCE_COMMIT SOURCE_CLEAN <<EOF
$(python3 - "$WHEEL" "$RECEIPT" "$ROOT_DIR" <<'PY'
from hashlib import sha256
from pathlib import Path
import json, sys
wheel, receipt, root = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()), Path(sys.argv[3])
sys.path.insert(0, str(root / "scripts"))
from verify_mcp_packages import package_source_identity
record = next(item for item in receipt["artifacts"] if item["path"].endswith(".whl"))
actual = sha256(wheel.read_bytes()).hexdigest()
if actual != record["sha256"]:
    raise SystemExit("wheel does not match MCP_CANDIDATE_RECEIPT.json")
candidate = receipt["candidate"]
current_digest, current_count = package_source_identity()
if current_digest != candidate["package_source_sha256"] or current_count != candidate["package_source_file_count"]:
    raise SystemExit("MCP_CANDIDATE_RECEIPT.json is stale relative to current package source")
print(actual, candidate["package_source_sha256"], candidate["source_commit"], str(candidate["source_tree_clean"]).lower())
PY
)
EOF

REVISION="$SOURCE_COMMIT"
if [[ "$SOURCE_CLEAN" != "true" ]]; then
  REVISION="${SOURCE_COMMIT}+package-${SOURCE_SHA:0:12}"
fi
EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$ROOT_DIR" show -s --format=%ct HEAD)}"
CREATED="$(python3 - "$EPOCH" <<'PY'
from datetime import datetime, timezone
import sys
print(datetime.fromtimestamp(int(sys.argv[1]), timezone.utc).isoformat().replace("+00:00", "Z"))
PY
)"

case "$WHEEL" in
  "$SERVER_DIR"/*) WHEEL_RELATIVE="${WHEEL#"$SERVER_DIR"/}" ;;
  *) echo "Candidate wheel must be inside $SERVER_DIR" >&2; exit 2 ;;
esac

SOURCE_DATE_EPOCH="$EPOCH" docker build \
  --provenance=false \
  --build-arg "SOURCE_DATE_EPOCH=$EPOCH" \
  --build-arg "PYTHON_IMAGE=$PYTHON_IMAGE" \
  --build-arg "CANDIDATE_WHEEL=$WHEEL_RELATIVE" \
  --build-arg "CANDIDATE_WHEEL_SHA256=$WHEEL_SHA" \
  --build-arg "PACKAGE_SOURCE_SHA256=$SOURCE_SHA" \
  --build-arg "OCI_REVISION=$REVISION" \
  --build-arg "OCI_VERSION=$VERSION" \
  --build-arg "OCI_CREATED=$CREATED" \
  --tag "$IMAGE" \
  --file "$SERVER_DIR/Dockerfile" \
  "$SERVER_DIR"

echo "Held local container: $IMAGE"
docker image inspect "$IMAGE" --format '{{.Id}} {{.Os}}/{{.Architecture}} {{.Size}} bytes'
echo "No registry publication, push, or deployment was performed."
