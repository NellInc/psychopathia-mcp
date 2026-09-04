# MCP release preparation and publication hold

This document is the current release contract for `psychopathia-mcp`.

## Current candidate

Version `0.1.0a7` was published to PyPI on 2026-09-04 from commit `ce31368` (receipt in `dist/MCP_CANDIDATE_RECEIPT.json`). It carries the MCP SDK 2.0.0 to 2.1.1 and uvicorn bumps, and the fix that makes the server advertise its own version on initialize instead of an empty string. `0.1.0a6` before it was a metadata-correcting release, published because Official MCP Registry versions are immutable and the registry's `0.1.0a5` record — written before the `a5` wheel existed — resolved to the `0.1.0a4` distribution; that `a5` record is deprecated. The public mirror `NellInc/psychopathia-mcp`, which every registry record names as `repository.url`, is synced at `0463633`. MCPB and container artifacts remain separate held actions.

Two sentences inside the published `0.1.0a7` artifacts are wrong and cannot be corrected, because PyPI files are immutable. The sdist's changelog section says "Candidate only. `0.1.0a6` remains the version PyPI serves", and the README that becomes the project page describes a7 as "a metadata-correcting release: its distribution is identical in content to `0.1.0a5`" — a6's rationale, reprinted under a7's number by a version substitution that edited the token inside hand-written prose. The distributed bytes are correct and the claim is only about the release's own description, so a7 is not yanked: yanking would resolve `pip install --pre` back to a6, which lacks the `serverInfo.version` fix. The generator now derives that sentence in full and `scripts/verify_mcp_packages.py` rejects an artifact whose README, METADATA, or changelog section makes a claim publication falsifies. Whether to spend an `0.1.0a8` on correcting the frozen project page is Nell's decision, not a maintenance default.

The public page reads the served version from `PUBLISHED_VERSION` and the candidate version from `pyproject.toml`. The invariant is that the *deployed* page never names a version PyPI does not serve: `PUBLISHED_VERSION` may be bumped in the same change as the candidate, but the distribution must be uploaded and verified on PyPI before `scripts/publish.sh` runs. Existing registry and package versions are historical external state and do not prove this candidate.

The package exposes stdio by default. An optional Streamable HTTP transport exists when installed with the `http` extra and explicitly enabled with `MCP_TRANSPORT=http`. The HTTP process binds to loopback by default and enforces host, origin, request-size, concurrency, and timeout limits. A public proxy remains responsible for TLS, authentication policy, edge limits, and operational monitoring.

## One-candidate preparation

Run from a clean, immutable commit after source gates pass:

```bash
python3 scripts/sync_mcp_metadata.py --check
python3 research/mcp/server/scripts/sync_data_for_wheel.py --check
python3 -m pip install --require-hashes -r research/mcp/server/requirements-build.lock
python3 -m build --no-isolation research/mcp/server
python3 -m twine check research/mcp/server/dist/*.whl research/mcp/server/dist/*.tar.gz
python3 scripts/verify_mcp_packages.py research/mcp/server/dist --ignore-mcpb
```

Regenerate `requirements-build.lock` only with the command recorded in its header. The lock is a universal Python 3.12 resolution so Linux-only keyring dependencies remain pinned and hashed even when regeneration occurs on macOS.

The verifier installs the wheel and sdist into isolated environments, exercises the protocol fixtures, and compares version, tool inventory, normalized outputs, and corpus digest. It emits checksums, an SBOM, and a candidate receipt. Keyword capability is the base acceptance gate. Semantic embedding capability is a separately reported optional state.

Build MCPB only from the accepted local wheel:

```bash
MCPB_BIN=/absolute/path/to/the/pinned/mcpb \
  research/mcp/server/scripts/build-mcpb.sh \
  research/mcp/server/dist/psychopathia_mcp-0.1.0a6-py3-none-any.whl
```

The MCPB CLI version and npm integrity must be recorded in the candidate receipt. Keep the top-level `"tools": []` workaround in `mcpb/manifest.json`; runtime discovery verifies the actual eleven tools.

Build a container only from the same wheel and a base image pinned by digest:

```bash
research/mcp/server/scripts/build-container.sh psychopathia-mcp:0.1.0a6-candidate-a
research/mcp/server/scripts/build-container.sh psychopathia-mcp:0.1.0a6-candidate-b
python3 scripts/verify_mcp_container.py \
  psychopathia-mcp:0.1.0a6-candidate-a \
  --equivalent-image psychopathia-mcp:0.1.0a6-candidate-b
```

Prepare the public repository tree without network or Git mutation:

```bash
research/mcp/server/scripts/sync-to-public.sh \
  --output dist/psychopathia-mcp-public-candidate
python3 scripts/build_mcp_release_set_receipt.py \
  --public-candidate dist/psychopathia-mcp-public-candidate
```

The preparation script verifies source parity, stages beside the repository,
writes `PUBLIC_SOURCE_CANDIDATE.json` and `PUBLIC_SOURCE_SHA256SUMS`, and installs
the tree atomically. It refuses to replace an unmarked directory. It contains
no clone, remote lookup, Git mutation, commit, push, upload, or deployment path.

## Required candidate receipt

The receipt records:

* full source commit and clean-tree state;
* package version and Python version;
* source corpus digest and bundled `DATA_MANIFEST.json` digest;
* wheel, sdist, MCPB, container, and public-source hashes where built;
* normalized tool inventory and fixture-output hashes for each format;
* dependency lock hashes and SBOM identities;
* base image digest, OCI labels, non-root user, offline protocol fixture, secure
  runtime flags, and deterministic container image identity;
* machine gate result;
* separate methodology, evidence, rights, security, human accessibility, and publication states.

No machine check can set a human or publication state to approved.

## Publication remains a separate action

After Nell verifies and explicitly authorizes the exact receipt, publish only the accepted bytes. Uploading to PyPI, mirroring the public repository, publishing MCPB or container artifacts, updating the Official MCP Registry or other catalogues, changing remote HTTP hosting, tagging, pushing, or deploying are outside candidate preparation and require fresh authorization.

Never combine build and upload in one command or script. Never rebuild from PyPI to create MCPB or container artifacts. Never use an unpinned `npx --yes` in a release path.

## The hosted endpoint the registry advertises

`server.json` advertises `https://mcp.psychopathia.ai/mcp`. That endpoint runs
from staged source on the shared `mcp-siblings` VM, not from the PyPI wheel, so
**upgrading the package does not refresh it** — the corpus is whatever was last
staged to `/opt/psychopathia/src/research/mcp`. Publishing a record without
refreshing the box points clients at corrected metadata over a stale corpus.

Upgrading it from `0.1.0a4` needs three things the old install did not, each of
which fails differently and none of which `systemctl is-active` catches:

1. **Dependencies.** `0.1.0a5+` needs MCP SDK 2.0 (`ServerRequestContext`).
   Installing the editable package with `--no-deps` leaves SDK 1.x in place and
   the unit crash-loops on import while `is-active` still reports `activating`.
   Install `requirements-base.lock` plus the `http` extra pins.
2. **`MCP_HTTP_ALLOWED_HOSTS`.** The HTTP transport enforces a Host allowlist
   defaulting to loopback only. The public proxy forwards the original Host, so
   the served name must be declared or every proxied request answers
   `400 Unrecognised Host`.
3. **`PSYCHOPATHIA_DATA_DIR`.** The loader takes an explicit data dir, else
   bundled `_data/`, else a walk-up only under `PSYCHOPATHIA_DATA_MODE=editable`.
   A staged-source install carries no `_data/`, so the corpus root must be named
   or every tool call returns `tool_failure`.

Both environment settings live in a systemd drop-in at
`/etc/systemd/system/psychopathia-mcp.service.d/allowed-hosts.conf`.

**What the box is staged from, as of 2026-09-04:** commit `ce31368`, package `0.1.0a7`, MCP SDK `2.1.1` — the released version, matching main. It does not follow main on its own: this state exists because it was re-staged deliberately, installing `requirements-base.lock` rather than `--no-deps`, which is what makes the SDK move with the release. Record the commit, package version and SDK here whenever you re-stage, so the next person can tell what is actually running from what main happens to say.

The check that proves a refresh landed is a corpus assertion through the public
name, not a liveness probe: `GET /mcp/` returning 405 and a successful
`initialize` both pass against a stale corpus. Call `resolve_id` for a migrated
id — `2.5` must answer `2.5::context-intercession`.

## Post-publication verification

After authorization and publication only:

1. Fetch each registry artifact and compare its digest with the approved receipt.
2. Install into fresh isolated environments outside a source checkout.
3. Verify bundled data mode, corpus digest, exact 79 identities, eleven tools, and normalized fixtures.
4. Verify the public repository tree against `PUBLIC_SOURCE_SHA256SUMS`.
5. Verify the HTTP endpoint separately, including TLS, authentication policy, headers, limits, and source candidate identity.
6. Store a publication receipt and rollback instructions.
