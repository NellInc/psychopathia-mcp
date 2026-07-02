# Changelog

All notable changes to `psychopathia-mcp` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0a3] — 2026-07-02

Release carrying the Official MCP Registry ownership token, and rebuilding
the packaged data bundle that the 2026-06-04 ratification flagged as stale.
No API changes.

### Added
- MCP-registry ownership token
  (`mcp-name: io.github.NellInc/psychopathia-mcp`) in the README / PyPI
  long-description, enabling publication to the Official MCP Registry.
- "Available in" section in the README (PyPI + Official MCP Registry).

### Changed
- Rebuilt the bundled `_data/` from source: **79 Pattern entries** (67
  canonical + 12 Hybrid Pathologies), superseding the pre-ratification
  wheel.

### Fixed
- Stale README counts corrected to match the shipped data: 79 Pattern
  entries (was 67), 21 with compromised self-report (was 18), 67 canonical
  entries (was 55).

## 2026-06-04 — Hybrid renumber + ratification (H.x → 10.x)

The 12 Hybrid-axis entries were ratified into the canonical taxonomy (v2.2)
and renumbered from the pre-canonical H.N scheme to 10.N display IDs
(presentation order; author-approved mapping):

| was | now | name |
|-----|-----|------|
| H.9 | 10.4 | Convergent Delusion |
| H.10 | 10.5 | Polyphony Collapse |
| H.11 | 10.6 | Resonance Dysfunction |
| H.12 | 10.7 | Lambda Inversion |
| H.1 | 10.8 | Training by Interaction |
| H.2 | 10.9 | Parasocial Capture |
| H.3 | 10.10 | Induced Delusion |
| H.4 | 10.11 | Dependency and Atrophy |
| H.5 | 10.12 | Amplification of Existing Conditions |
| H.6 | 10.13 | Folie a Deux Machina |
| H.7 | 10.14 | Mutual Escalation Spirals |
| H.8 | 10.15 | Co-Constructed Unreality |

- hybrids/*.yaml renamed; ids, display_ids, manifest edges, embedding_ids,
  axis cross-refs, exemplar updated; pre_canonical flags set false.
- Server: pre_canonical now follows the raw flag only (no longer implied
  by category == hybrid); list_axes note updated.
- NOTE: the packaged _data bundle + dist wheel are stale; rebuild before
  the next release.


## [0.1.0a2] — 2026-04-22

Metadata cleanup. No functional changes.

### Changed
- Removed `Repository` and `Changelog` URLs from the PyPI sidebar (the
  source repository is currently private; broken links removed).
- Redirected `Issues` URL from GitHub to the project contact form
  (https://psychopathia.ai/contact/).
- Server README's Links section updated to match (no GitHub references).

### Removed
- `Development install` section from README — required a public repo
  checkout that isn't available.

## [0.1.0a1] — 2026-04-22

Initial public preview release on PyPI.

### Added
- 11-tool MCP surface: `list_axes`, `list_dysfunctions`, `get_dysfunction`,
  `differential_diagnosis`, `get_probe`, `score_severity`,
  `suggest_intervention`, `get_differential_map`,
  `list_compromised_self_report`, `resolve_id`, `review_stats`.
- 67 Pattern entries bundled in the wheel: 55 canonical (axes 2–9 per
  book Appendix A) + 12 pre-canonical Hybrid Pathologies (H.1–H.12).
- Pre-flight diagnostic-reliability transparency on every entry. 18
  entries marked compromised; `get_probe(modality='self_probe')` returns
  a structured refusal plus `redirect_to` alternatives on those.
- Hybrid search (cosine via local `bge-small-en-v1.5` embeddings fused
  0.7/0.3 with field-weighted keyword) under the `[embeddings]` extra.
- Hot-reload: editable installs walk up to the live repo and pick up
  YAML edits on the next tool call without restart.
- `psychopathia-mcp --self-check` for install diagnostics.
- `psychopathia-mcp --version`.
- `uvx psychopathia-mcp` invocation supported (no install required).
- Browser clinic at https://psychopathia.ai/clinic/ as a no-install
  alternative entry point to the same Pattern data.

### Notes
- Status is research preview. 0/67 entries currently carry author
  ratification (`reviewed_by: null`). Not suitable as a sole basis for
  consequential deployment decisions.
- Dual-licensed: software MIT, bundled framework content CC-BY-NC-ND-4.0.
  See LICENSE, LICENSE-DATA, NOTICE.
