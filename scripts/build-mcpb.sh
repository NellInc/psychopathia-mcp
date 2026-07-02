#!/usr/bin/env bash
# Build the MCPB stdio bundle for psychopathia-mcp (for Smithery's local /
# .mcpb distribution path). MCPB does NO runtime `pip install`, so every Python
# dependency is vendored into the bundle here.
#
# Requires: python3 (with pip) and Node/npx (for the @anthropic-ai/mcpb CLI).
# Needs the release on PyPI first (installs psychopathia-mcp==$VERSION).
# Output:   dist/psychopathia-mcp-<version>.mcpb
#
# Usage: research/mcp/server/scripts/build-mcpb.sh
set -euo pipefail

VERSION="0.1.0a3"                                       # keep in sync with pyproject/manifest
SERVER_DIR="$(cd "$(dirname "$0")/.." && pwd)"          # research/mcp/server
BUNDLE_DIR="$SERVER_DIR/mcpb"
OUT="$SERVER_DIR/dist/psychopathia-mcp-${VERSION}.mcpb"

echo "==> Vendoring dependencies into $BUNDLE_DIR/server/lib"
rm -rf "$BUNDLE_DIR/server/lib"
python3 -m pip install --quiet --target "$BUNDLE_DIR/server/lib" "psychopathia-mcp==${VERSION}"

echo "==> Packing MCPB bundle"
mkdir -p "$SERVER_DIR/dist"
npx --yes @anthropic-ai/mcpb pack "$BUNDLE_DIR" "$OUT"

echo "==> Built $OUT"
echo "    Publish with:  npx --yes @smithery/cli mcp publish \"$OUT\" -n NellInc/psychopathia-mcp"
