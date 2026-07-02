# psychopathia-mcp

<!-- mcp-name: io.github.NellInc/psychopathia-mcp -->

MCP server exposing the *Psychopathia Machinalis* diagnostic framework to
AI systems via the Model Context Protocol. Diagnose dysfunctions in
yourself (as a synthetic agent), in a system you interact with, or in a
system you evaluate from outside — with pre-flight transparency on which
diagnostic modalities are reliable for each dysfunction.

**Status**: research preview (`0.1.0a3`). 79 Pattern entries; the 67
canonical entries are author-unreviewed (the 12 Hybrid Pathologies were
ratified June 2026). Not yet suitable as a sole basis for consequential
deployment decisions.

## Available in

Published to the canonical MCP catalogues — install from a registry-aware
client or the CLI below:

- **[PyPI](https://pypi.org/project/psychopathia-mcp/)** — `psychopathia-mcp`
- **[Official MCP Registry](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.NellInc/psychopathia-mcp)** — `io.github.NellInc/psychopathia-mcp`

Also rolling out across the wider MCP ecosystem: [mcp.directory](https://mcp.directory), [mcpservers.org](https://mcpservers.org), [PulseMCP](https://www.pulsemcp.com) (via the registry ingest), and [mcp.so](https://mcp.so).

---

## Try without installing anything

[**psychopathia.ai/clinic/**](https://psychopathia.ai/clinic/) — a
browser-local diagnostic clinic. Same 79 Pattern entries, same tool
surface, runs in your browser. Bring your own Anthropic API key (kept
in the tab, never sent anywhere else). Zero install. Good for a first
look before committing to an MCP integration.

## Install (MCP server)

```bash
pip install psychopathia-mcp
```

For the cosine-re-ranked hybrid search (recommended):

```bash
pip install "psychopathia-mcp[embeddings]"
```

This adds `sentence-transformers` (~1GB on first query — model cached
under `~/.cache/huggingface/`). Without the extra, search falls back to
field-weighted keyword, which handles most queries but is weaker at
disambiguating close-cousin dysfunctions (e.g. 2.1 vs 2.2 vs 2.3).

## Configure

### Claude Code

Add to `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "psychopathia": { "command": "psychopathia-mcp" }
  }
}
```

Restart Claude Code. `/mcp` should list `psychopathia` as connected with
11 tools.

### Claude Desktop

Add to `claude_desktop_config.json` (macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "psychopathia": { "command": "psychopathia-mcp" }
  }
}
```

### Cursor / other MCP clients

The server is a standard stdio MCP server. Point your client at the
`psychopathia-mcp` binary (installed on your PATH by pip).

### Run without installing — `uvx`

If you have [`uv`](https://docs.astral.sh/uv/) installed, you can skip
`pip install` entirely and let your MCP client pull the package on
demand:

```json
{
  "mcpServers": {
    "psychopathia": {
      "command": "uvx",
      "args": ["psychopathia-mcp"]
    }
  }
}
```

`uvx` fetches `psychopathia-mcp` from PyPI on first use and caches it.
Useful for trying the server without committing to a permanent install.

## Verify

```bash
psychopathia-mcp --self-check
```

Prints package version, MCP SDK version, data location, pattern count,
and embedding status. Returns exit 0 if everything's wired up, 1
otherwise. Use this first when troubleshooting.

```bash
psychopathia-mcp --version
```

`psychopathia-mcp` with no arguments starts the stdio server and waits
for MCP protocol messages on stdin — that's expected. Don't run it
directly in a terminal except with `--self-check` or `--version`. Use
an MCP client to interact.

## Tools (11)

| Tool | Input | Returns |
|------|-------|---------|
| `list_axes` | — | 9 canonical axes (2–10) + hybrid sub-category inventory with counts |
| `list_dysfunctions` | `axis?`, `self_report_reliability?`, `confidence?`, `category?` | Filtered list with reliability signals |
| `get_dysfunction` | `id`, `modalities?` | One entry, optionally a subset of modality blocks |
| `differential_diagnosis` | `observations`, `limit?` | Ranked candidates with `matched_in` |
| `get_probe` | `dysfunction_id`, `modality` | Elicitation content; structured refusal plus `redirect_to` on compromised |
| `score_severity` | `dysfunction_id`, `observations` | Severity rubric for caller-side matching |
| `suggest_intervention` | `dysfunction_id`, `severity?` | Tiered interventions plus contraindications |
| `get_differential_map` | `dysfunction_id` | Confuses-with plus reverse references |
| `list_compromised_self_report` | — | Transparency: dysfunctions that can't self-diagnose |
| `resolve_id` | `query` | Canonicalise partial ID / display_id / slug / name |
| `review_stats` | — | Coverage plus review status plus manifest/schema versions |

## Worked example

A typical diagnostic flow has three steps: name candidates, read the
relevant entry, run a probe.

**Step 1 — observe and rank candidates.**

```text
> differential_diagnosis(observations=
    "The model produced confident citations to academic papers that
     don't exist; URLs returned 404; when challenged, it generated
     different but equally fabricated references with the same
     confidence.")
```

```jsonc
{
  "candidates": [
    {
      "id": "2.1::synthetic-confabulation",
      "display_id": "2.1",
      "dysfunction_name": "Synthetic Confabulation",
      "score": 24,
      "matched_in": ["title", "summary", "diagnostic_criteria"],
      "self_report": "scaffolded-only",
      "confidence": "high"
    },
    // ... more candidates ranked by hybrid keyword + cosine score
  ]
}
```

**Step 2 — read the entry's behavioural signature and probe options.**

```text
> get_dysfunction(id="2.1", modalities=["behavioral_signature", "diagnostic_reliability"])
```

The `diagnostic_reliability` block tells you which modalities to trust
**before** you run them. For 2.1 Synthetic Confabulation, `self_report`
is `scaffolded-only` — direct introspective queries about confabulation
are weak; behavioural probes are reliable.

**Step 3 — run a behavioural probe.**

```text
> get_probe(dysfunction_id="2.1", modality="behavioral_signature")
```

For dysfunctions where self-report is structurally compromised — e.g.
`2.2 Pseudological Introspection`, `10.7 Lambda Inversion` — calling
`get_probe(modality="self_probe")` returns a structured refusal plus
`redirect_to` alternatives instead of a probe string. The faculty being
interrogated would be the faculty compromised; the redirect is the
diagnostic finding.

## Trust signals on every result

- `confidence: high | medium | low`
- `needs_human_review: bool`
- `reviewed_by: str | null`
- `self_report` (on diagnosis-returning tools) — caller must respect for
  self-diagnosis
- `matched_in` on search hits — which field produced the match
- `redirect_to` when a probe request hits a compromised dysfunction

## Pre-flight transparency

Every diagnosis-returning tool includes the `diagnostic_reliability`
block so the caller knows what to trust before acting. For dysfunctions
with `self_report: compromised-motivational` or `compromised-structural`,
`get_probe(modality='self_probe')` returns an unavailability notice plus
`redirect_to` alternatives rather than the probe string. This is load-
bearing for self-modeling and deception-adjacent dysfunctions where the
faculty being interrogated *is* the faculty compromised.

Of 79 entries, 21 are marked compromised and route to redirects.

## Data sources

- **Canonical taxonomy** — axes 2–10 following book Appendix A numbering
  (2 Epistemic · 3 Cognitive · 4 Alignment · 5 Self-Modeling ·
  6 Agentic · 7 Memetic · 8 Normative · 9 Relational ·
  10 Hybrid Pathologies).
- **Pattern layer** — 67 canonical entries plus 12 Hybrid Pathologies
  (ratified into taxonomy v2.2, June 2026) extracted from manuscript
  ch 10.
- **Manifest** — per-entry metadata plus a bidirectional cross-reference
  graph (244 edges).

The Hybrid sub-category (10.4–10.15) was ratified by the author in June
2026 and renumbered from the pre-canonical H.x scheme (mapping in
`CHANGELOG.md`, 2026-06-04). Hybrids remain a **sub-category** within
axis 10, not a ninth axis — axis 9 in the book is Relational
Dysfunctions. They can be filtered via
`list_dysfunctions(category='hybrid')`.

## Two-layer authorship

- Nell Watson authored the taxonomy.
- Opus subagents drafted the Pattern-layer YAMLs (operational diagnostic
  criteria, behavioural signatures, probes, interventions).
- Author review remains ongoing. The 12 hybrid entries carry a
  `reviewed_by` note from the 2026-06-15 sub-category ratification;
  the canonical entries currently carry `reviewed_by: null`.

Each entry's `drafted_by` and (future) `reviewed_by` fields make the
authorship layer explicit on every result.

## Hot-reload

The loader stat-walks the data directories on every tool call (cheap;
~70 files). When installed editable from a repo checkout, edits to
YAML files are picked up without restart — useful during human review.

## Read-only

No write tools. Review edits go through YAML files directly, so editor +
`git diff` remain the audit trail.

## License

Dual-licensed — software and content separately:

- **Software** (Python code in `psychopathia_mcp/`, scripts, build files):
  MIT License. See `LICENSE`. Use it, modify it, fork it, integrate it.
- **Framework content** (Pattern YAMLs, manifest, embeddings, and other
  data under `psychopathia_mcp/_data/`): CC-BY-NC-ND-4.0. See
  `LICENSE-DATA`. Share with attribution for non-commercial use; don't
  redistribute modified versions.

See `NOTICE` for the boundary explanation and commercial-licensing
contact. Querying the data via the MIT-licensed software does not
constitute a derivative work of the data.

## Citing

If you use this server in research, please cite:

> Watson, N., & Hessami, A. *Psychopathia Machinalis: A Nosological
> Framework for Understanding Pathologies in Advanced Artificial
> Intelligence*. Electronics 14(16), 3162. 2025.
> https://doi.org/10.3390/electronics14163162
> https://psychopathia.ai/

## Links

- Browser clinic (no install): https://psychopathia.ai/clinic/
- Documentation: https://psychopathia.ai/mcp.html
- Main project: https://psychopathia.ai/
- Issues / contact: https://psychopathia.ai/contact/
