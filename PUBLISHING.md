# MCP release preparation and publication hold

This document is the current release contract for `psychopathia-mcp`.

## Current candidate

Version `0.1.0a6` is the current candidate: a metadata-correcting release whose distribution is identical in content to `0.1.0a5` (uploaded to PyPI on 2026-09-04 from commit 31deaeb, receipt in `dist/MCP_CANDIDATE_RECEIPT.json`). It exists because Official MCP Registry versions are immutable and the registry's `0.1.0a5` record — published before the `a5` wheel existed — resolves to the `0.1.0a4` distribution, so registry clients installed the pre-sweep corpus. Publishing `0.1.0a6` against the current wheel corrects that, after which the `a5` registry record is marked deprecated with `mcp-publisher status`. MCPB, container and public-repository mirroring remain separate held actions.

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

## Post-publication verification

After authorization and publication only:

1. Fetch each registry artifact and compare its digest with the approved receipt.
2. Install into fresh isolated environments outside a source checkout.
3. Verify bundled data mode, corpus digest, exact 79 identities, eleven tools, and normalized fixtures.
4. Verify the public repository tree against `PUBLIC_SOURCE_SHA256SUMS`.
5. Verify the HTTP endpoint separately, including TLS, authentication policy, headers, limits, and source candidate identity.
6. Store a publication receipt and rollback instructions.
