#!/usr/bin/env bash
# Build a cross-platform MCPB v0.4 candidate around the exact accepted wheel.
# uv resolves the hash-locked environment at install time. No package is
# fetched from PyPI in place of the candidate wheel, and no publication occurs.
set -euo pipefail

SERVER_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ROOT_DIR="$(cd "$SERVER_DIR/../../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
MCPB_BIN="${MCPB_BIN:-}"
UV_BIN="${UV_BIN:-}"
MCPB_VERSION="2.1.2"
UV_VERSION="0.12.3"

if [[ -z "$MCPB_BIN" || ! -x "$MCPB_BIN" ]]; then
  echo "MCPB_BIN must name the pinned @anthropic-ai/mcpb executable." >&2
  exit 2
fi
if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  echo "UV_BIN must name the pinned uv executable." >&2
  exit 2
fi
[[ "$($MCPB_BIN --version)" == "$MCPB_VERSION" ]] || {
  echo "Expected MCPB CLI $MCPB_VERSION." >&2; exit 2;
}
[[ "$($UV_BIN --version)" == "uv $UV_VERSION"* ]] || {
  echo "Expected uv $UV_VERSION." >&2; exit 2;
}

VERSION="$($PYTHON_BIN -c 'import tomllib,pathlib; print(tomllib.loads(pathlib.Path("'"$SERVER_DIR"'/pyproject.toml").read_text())["project"]["version"])')"
WHEEL="${1:-$SERVER_DIR/dist/psychopathia_mcp-${VERSION}-py3-none-any.whl}"
OUT="${2:-$SERVER_DIR/dist/psychopathia-mcp-${VERSION}.mcpb}"
RECEIPT="$SERVER_DIR/dist/MCP_CANDIDATE_RECEIPT.json"
[[ -f "$WHEEL" ]] || { echo "Candidate wheel not found: $WHEEL" >&2; exit 2; }
[[ -f "$RECEIPT" ]] || { echo "Verify wheel and sdist before building MCPB." >&2; exit 2; }

TMP="$($PYTHON_BIN -c 'import tempfile; print(tempfile.mkdtemp(prefix="pm-mcpb-build-"))')"
cleanup() {
  "$PYTHON_BIN" - "$TMP" <<'PY'
from pathlib import Path
import shutil, sys
p = Path(sys.argv[1])
if p.exists():
    shutil.rmtree(p)
PY
}
trap cleanup EXIT

echo "==> Verifying release-tool and wheel identities"
"$PYTHON_BIN" - "$SERVER_DIR" "$WHEEL" "$RECEIPT" <<'PY'
from pathlib import Path
from hashlib import sha256
import json, sys
server, wheel, receipt = map(Path, sys.argv[1:])
lock = json.loads((server / "release-tools/mcpb/package-lock.json").read_text())
tool = lock["packages"]["node_modules/@anthropic-ai/mcpb"]
assert tool["version"] == "2.1.2"
assert tool["integrity"] == "sha512-goRbBC8ySo7SWb7tRzr+tL6FxDc4JPTRCdgfD2omba7freofvjq5rom1lBnYHZHo6Mizs1jAHJeN53aZbDoy8A=="
expected = json.loads(receipt.read_text())
record = next(item for item in expected["artifacts"] if item["path"].endswith(".whl"))
assert sha256(wheel.read_bytes()).hexdigest() == record["sha256"]
sys.path.insert(0, str(server.parents[2] / "scripts"))
from verify_mcp_packages import package_source_identity
current_digest, current_count = package_source_identity()
candidate = expected["candidate"]
assert current_digest == candidate["package_source_sha256"]
assert current_count == candidate["package_source_file_count"]
PY

echo "==> Preparing an MCPB v0.4 uv project around the local wheel"
"$PYTHON_BIN" - "$SERVER_DIR/mcpb/server" "$WHEEL" "$VERSION" "$SERVER_DIR/requirements-base.lock" <<'PY'
from pathlib import Path
import re, shutil, sys
target, wheel, version, base_lock = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
if target.exists():
    shutil.rmtree(target)
target.mkdir(parents=True)
name = wheel.name
shutil.copy2(wheel, target / name)
# The bundle floor is 3.11 because the base lock's own pins (rpds-py) require
# it; a wider floor makes uv resolve extra splits the pins cannot satisfy.
# The base lock is the source of truth for transitive versions. Feeding its
# pins to uv as constraints keeps the bundle from drifting whenever a
# dependency publishes a new release between lock refreshes; the later
# uv/base comparison then verifies the constraint held rather than racing it.
pins = re.findall(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)", base_lock.read_text(encoding="utf-8"), re.M)
constraints = ",\n".join(f'  "{pkg}=={ver}"' for pkg, ver in pins)
(target / "pyproject.toml").write_text(f'''[project]
name = "psychopathia-mcp-bundle"
version = "{version}"
requires-python = ">=3.11"
dependencies = [
  "psychopathia-mcp=={version}",
  "starlette==1.6.0",
  "uvicorn==0.52.1",
]

[tool.uv]
package = false
constraint-dependencies = [
{constraints}
]

[tool.uv.sources]
psychopathia-mcp = {{ path = "{name}" }}
''', encoding="utf-8")
PY

"$UV_BIN" lock --directory "$SERVER_DIR/mcpb/server" --python "$PYTHON_BIN"
"$PYTHON_BIN" - "$SERVER_DIR" "$WHEEL" <<'PY'
from pathlib import Path
from hashlib import sha256
import re, sys, tomllib
server, wheel = Path(sys.argv[1]), Path(sys.argv[2])
uv_lock = tomllib.loads((server / "mcpb/server/uv.lock").read_text())
packages = {item["name"]: item for item in uv_lock["package"]}
candidate = packages["psychopathia-mcp"]
assert candidate["source"]["path"] == wheel.name
assert candidate["wheels"][0]["hash"] == "sha256:" + sha256(wheel.read_bytes()).hexdigest()
base = {}
for name, version in re.findall(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)", (server / "requirements-base.lock").read_text(), re.M):
    base[name.lower().replace("_", "-")] = version
uv_versions = {name: item["version"] for name, item in packages.items() if "version" in item}
for name, version in base.items():
    if name in uv_versions and uv_versions[name] != version:
        raise SystemExit(f"uv/base lock mismatch for {name}: {uv_versions[name]} != {version}")
PY

echo "==> Exercising the bundled wheel through the frozen uv project"
UV_PROJECT_ENVIRONMENT="$TMP/venv" \
  "$UV_BIN" sync --directory "$SERVER_DIR/mcpb/server" --frozen --python "$PYTHON_BIN"
SELF_CHECK="$(UV_PROJECT_ENVIRONMENT="$TMP/venv" "$UV_BIN" run --directory "$SERVER_DIR/mcpb/server" --frozen psychopathia-mcp --self-check --json)"
"$PYTHON_BIN" - "$SELF_CHECK" "$VERSION" <<'PY'
import json, sys
report = json.loads(sys.argv[1])
assert report["version"] == sys.argv[2]
assert report["data_mode"] == "bundled"
assert report["keyword_ready"] is True
assert report["semantic_ready"] is False
assert report["counts"] == {"total": 79, "canonical": 67, "hybrid": 12, "axes": 9}
assert report["errors"] == []
PY

"$PYTHON_BIN" "$ROOT_DIR/scripts/sync_mcp_metadata.py" --check
"$MCPB_BIN" validate "$SERVER_DIR/mcpb/manifest.json"

echo "==> Packing with the pinned MCPB CLI, then normalising ZIP metadata"
RAW="$TMP/raw.mcpb"
"$MCPB_BIN" pack "$SERVER_DIR/mcpb" "$RAW"
mkdir -p "$(dirname "$OUT")"
"$PYTHON_BIN" - "$RAW" "$OUT" "${SOURCE_DATE_EPOCH:-0}" <<'PY'
from pathlib import Path
from datetime import datetime, timezone
import sys, zipfile
source, output, epoch = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
if output.exists():
    output.unlink()
stamp = datetime.fromtimestamp(epoch or 315532800, timezone.utc)
stamp = max(stamp, datetime(1980, 1, 1, tzinfo=timezone.utc))
date_time = (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second)
with zipfile.ZipFile(source) as read, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as write:
    for old in sorted(read.infolist(), key=lambda item: item.filename):
        name = old.filename
        if name.startswith("/") or ".." in Path(name).parts:
            raise SystemExit(f"unsafe MCPB member: {name}")
        info = zipfile.ZipInfo(name, date_time)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = old.create_system
        info.external_attr = old.external_attr
        info.flag_bits = old.flag_bits
        write.writestr(info, read.read(old))
PY

UNPACKED="$TMP/unpacked"
"$MCPB_BIN" unpack "$OUT" "$UNPACKED"
"$MCPB_BIN" validate "$UNPACKED/manifest.json"
"$MCPB_BIN" info "$OUT"
"$PYTHON_BIN" - "$OUT" "$WHEEL" <<'PY'
from pathlib import Path
from hashlib import sha256
import sys, zipfile
bundle, wheel = Path(sys.argv[1]), Path(sys.argv[2])
with zipfile.ZipFile(bundle) as archive:
    names = archive.namelist()
    member = f"server/{wheel.name}"
    assert member in names
    assert sha256(archive.read(member)).hexdigest() == sha256(wheel.read_bytes()).hexdigest()
    assert "server/uv.lock" in names and "server/pyproject.toml" in names
    assert not any(".venv/" in name or "server/lib/" in name for name in names)
PY

echo "==> Held MCPB candidate: $OUT"
shasum -a 256 "$OUT"
echo "No upload, registry publication, push, or deployment was performed."
