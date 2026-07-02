# Publishing `psychopathia-mcp` to MCP registries

Release runbook for the Psychopathia Machinalis MCP server. Ordered so one
publish cascades: the **Official MCP Registry** is the keystone — PulseMCP
ingests it daily and mcp.directory auto-discovers it, so publishing there seeds
several directories at once with a namespace-verified listing.

Transport is **stdio-only**. That is a non-issue at every registry below — none
require HTTP/SSE for a local server.

> **Public server repo (2026-07-02):** the monorepo `github.com/NellInc/psychopathia`
> is private, so the MCP server was split into a dedicated **PUBLIC** repo —
> **https://github.com/NellInc/psychopathia-mcp** (server at the repo ROOT; mirrored
> from this directory by `scripts/sync-to-public.sh`). Point every directory link,
> Glama, and Docker at that public repo — **not** the private monorepo, and **not** a
> `/tree/main/research/mcp/server` subdir (there is none; the server is at the root).
> This unblocks **Glama** and the **Docker MCP Catalog** (they can now clone it).
> The Official Registry entry still carries the private `repository.url` (published
> before the split); re-publish to refresh it, or rely on the public repo directly.

---

## 0. Cut a release (do this first for any new version)

The ownership token the Official Registry needs lives in the **immutable** PyPI
description, so every registry change rides on a PyPI release. PyPI releases are
immutable — you cannot edit a description after upload, so a new version is
mandatory even when the code is unchanged.

```bash
cd research/mcp/server
python3 scripts/sync_data_for_wheel.py    # bundle manifest + 79 pattern YAMLs + embeddings into _data/
rm -f dist/*.whl dist/*.tar.gz
uv build                                   # or: python3 -m build
python3 -m twine upload dist/psychopathia_mcp-<version>-py3-none-any.whl dist/psychopathia_mcp-<version>.tar.gz
```

Verify the upload carries the license + ownership token:

```bash
curl -s https://pypi.org/pypi/psychopathia-mcp/<version>/json | python3 -c "
import sys,json; i=json.load(sys.stdin)['info']
print('token present:', 'mcp-name: io.github.NellInc/psychopathia-mcp' in (i.get('description') or ''))"
```

Bump `version` in `pyproject.toml`, `psychopathia_mcp/__init__.py`, `server.json`,
`mcpb/manifest.json`, `scripts/build-mcpb.sh`, and the `Dockerfile` pin together.

> **Status: 0.1.0a3 built + verified locally, upload PENDING (Nell's PyPI token).**
> The wheel carries `License: MIT` + all three license files, the `mcp-name`
> ownership token in METADATA, and the full 79-pattern `_data` bundle; it imports
> and loads 79 patterns / 11 tools from a clean venv outside the repo. Run the
> `twine upload` above to make it live, then §1 is unblocked.

---

## 1. Official MCP Registry — keystone  ·  effort: low

Manifest committed at `research/mcp/server/server.json`
(name `io.github.NellInc/psychopathia-mcp`, PyPI package, stdio transport,
`0.1.0a3`). `mcp-publisher validate` passes against the live schema.

The registry does a **case-sensitive** namespace match against your GitHub login
`NellInc` (verified in `modelcontextprotocol/registry` `internal/auth/github_at.go`
+ `jwt.go` — `strings.HasPrefix`, no lowercasing). So the casing in `server.json`,
the README token, and the authenticated identity must all be exactly
`io.github.NellInc/...`. Lowercase fails the publish.

```bash
brew install mcp-publisher            # already installed on this machine
cd research/mcp/server
mcp-publisher login github            # device flow — authenticate as NellInc at github.com/login/device
mcp-publisher publish                 # uses ./server.json
# verify:
curl -s 'https://registry.modelcontextprotocol.io/v0/servers?search=io.github.NellInc/psychopathia-mcp' \
  | python3 -c "import sys,json; s=json.load(sys.stdin)['servers']; print(s[0]['server']['name'], s[0]['server']['version']) if s else print('NOT FOUND')"
```

**Acceptance:** the curl prints `io.github.NellInc/psychopathia-mcp 0.1.0a3`.

---

## 2. PulseMCP  ·  effort: none (automatic)  ·  via Official Registry

PulseMCP no longer has a direct server-submission form; its "Submit → MCP Server"
flow only **ingests the Official MCP Registry daily**. So publishing §1 *is* the
PulseMCP submission — nothing else to do. For corrections to an existing listing,
email `hello@pulsemcp.com`. (Its /submit page also reCAPTCHA-blocks automation
browsers.)

---

## 3. mcp.directory — <https://mcp.directory/submit>  ·  anonymous form

mcp.directory **auto-ingests Official Registry entries**, so §1 should seed an
accurate, namespace-verified listing on its own. The manual form is a backstop.
Its crawler reads the repo you give it — but ours is **private**, so rely on the
PyPI package + an explicit description rather than a GitHub crawl:

- GitHub Repository URL: `https://github.com/NellInc/psychopathia-mcp`
- **PyPI** Package: `psychopathia-mcp`  ·  **npm**: *(leave blank)*
- Short Description (≤100 chars): `Psychopathia Machinalis: diagnose AI dysfunctions — 79 conditions, 11 read-only stdio tools.`
- Email: `nell@ethicsnet.com`

---

## 4. mcpservers.org — <https://mcpservers.org/submit>  ·  anonymous form

Web front-end for `wong2/awesome-mcp-servers`; submit via the form (author-typed,
no mis-scrape). Use the **PyPI** link, not the private GitHub URL:

- Name: `psychopathia-mcp`
- Description: `Read-only MCP server for the Psychopathia Machinalis diagnostic framework (79 conditions) — differential diagnosis of AI dysfunctions via 11 tools; Python stdio.`
- Link: `https://pypi.org/project/psychopathia-mcp/`  ← PyPI (repo is private)
- Category: `Development` (or `Other`)
- Email: `nell@ethicsnet.com`

---

## 5. mcp.so — <https://mcp.so/submit>  ·  requires sign-in  ·  do in a normal browser

The /submit form **requires signing in** (Google or GitHub) before it accepts a
submission. OAuth does **not** persist in an automation browser (the GitHub
callback lands on `about:blank`, no session cookie), so **submit from your normal
browser**, where your GitHub session already exists.

- **Type:** `MCP Server`
- **Name:** `psychopathia-mcp`
- **URL:** `https://psychopathia.ai/mcp.html`  *(the repo is private; use the public guide, not a github.com/... link that would 404)*
- **Avatar image URL:** `https://www.psychopathia.ai/assets/figures/apple-touch-icon.png`  *(use the **www** host — the apex 301-redirects and some avatar fetchers don't follow redirects; verified 200 image/png 2026-07-02)*
- **Tags:** `ai-diagnosis, ai-safety, ai-welfare, psychopathia-machinalis, nosology, mcp`
- **Server Config:** `{"mcpServers":{"psychopathia":{"command":"uvx","args":["psychopathia-mcp"]}}}`
- **Content** (markdown body):

```markdown
**Psychopathia Machinalis MCP** serves a diagnostic nosology of AI dysfunctions
to AI systems over the Model Context Protocol.

It exposes **79 conditions** (67 canonical across 9 axes + 12 Hybrid Pathologies)
through **11 read-only tools** — differential diagnosis, per-dysfunction probes,
severity scoring, intervention suggestions, and a cross-reference graph. Every
result carries pre-flight **diagnostic-reliability** signals: for the 21 entries
whose self-report is structurally compromised, a self-probe returns a refusal
plus `redirect_to` alternatives instead of a misleading answer.

**Highlights**
- Read-only, no auth, no external calls — framework data is bundled in the package
- stdio transport · Python ≥3.10 · MIT-licensed code (CC-BY-NC-ND framework content)

**Install**

    uvx psychopathia-mcp

(or `pip install psychopathia-mcp`)

**Config**

    {"mcpServers":{"psychopathia":{"command":"uvx","args":["psychopathia-mcp"]}}}

Try it with no install at the browser clinic: https://psychopathia.ai/clinic/
More: https://psychopathia.ai/mcp.html
```

---

## 6. Glama  ·  effort: low  ·  BLOCKED while the repo is private

`glama.json` (maintainer `NellInc`) is committed at the repo root, and the
subdirectory `Dockerfile` de-risks Glama's sandbox build. **But Glama clones the
GitHub repo to scan/build it, so it cannot list a private repo.** Do this only
after `NellInc/psychopathia` is made public:

- Sign in at <https://glama.ai> via GitHub OAuth (needs write/admin on the repo).
- **Add Server** with `https://github.com/NellInc/psychopathia-mcp`.
- **Sync Server** to trigger an immediate scan.

---

## 7. Smithery — via MCPB stdio bundle  ·  effort: low–med  ·  optional (works while private)

Smithery's `smithery.yaml` is for its hosted/container path (needs an HTTP
transport we don't have). The route for a stdio server is a self-contained **MCPB
bundle** — which does **not** depend on the repo, so it works even while private.
Build with `scripts/build-mcpb.sh` (manifest `mcpb/manifest.json` spec `0.3`,
launcher `mcpb/server/main.py`; deps vendored because MCPB does no runtime install).
Requires the release on PyPI first.

```bash
cd research/mcp/server
bash scripts/build-mcpb.sh            # → dist/psychopathia-mcp-<version>.mcpb
npx --yes @smithery/cli login
npx --yes @smithery/cli mcp publish dist/psychopathia-mcp-<version>.mcpb -n NellInc/psychopathia-mcp
```

---

## 8. Docker MCP Catalog  ·  effort: medium  ·  BLOCKED while the repo is private

A PyPI-based `Dockerfile` is committed in this directory. Submission is a PR to
[`docker/mcp-registry`](https://github.com/docker/mcp-registry) whose `task create`
wizard builds the image from a **repo** Dockerfile and verifies it lists tools —
which needs the source repo to be reachable. Do this after the repo is public, or
via the pre-built-image path (`task create -- --image ...`).

**Caveat:** `task create` builds from a Dockerfile at the **repo root**, but ours
is in `research/mcp/server/`. Since the Dockerfile is PyPI-based (location-
independent), copy it to root on a submission branch or use the `--image` path.

---

## Status (2026-07-02)

- ⏳ **PyPI `0.1.0a3`** — built + verified locally; `twine upload` PENDING (Nell's token).
- ⏳ **Official MCP Registry** — `server.json` committed + `validate` passes; `mcp-publisher login/publish` PENDING (device flow as NellInc).
- ⬜ **PulseMCP** — automatic via the registry ingest once §1 lands (no form).
- ⬜ **mcp.directory** — auto-discovers the registry; manual form is a backstop (repo private → rely on PyPI + description).
- ⬜ **mcpservers.org** — anonymous form; use the PyPI link.
- ⬜ **mcp.so** — sign-in required; submit from a normal browser; link to psychopathia.ai/mcp.html.
- 🚫 **Glama** — blocked while `NellInc/psychopathia` is private (clones the repo).
- ⬜ **Smithery** — MCPB bundle (self-contained; works while private); needs PyPI release first.
- 🚫 **Docker MCP Catalog** — blocked while the repo is private (builds from a repo Dockerfile).
