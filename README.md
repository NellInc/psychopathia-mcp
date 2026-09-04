# psychopathia-mcp

<!-- mcp-name: io.github.NellInc/psychopathia-mcp -->

Read only Model Context Protocol access to the *Psychopathia Machinalis*
research framework. The server lets a caller inspect 79 Pattern entries,
compare observed behaviour with draft operational guidance, retrieve bounded
probe material, and see reliability, evidence, and review status before use.

**Candidate status:** `0.1.0a7` is a metadata-correcting release: its
distribution is identical in content to `0.1.0a5`, and it exists because
Official MCP Registry versions are immutable and the registry's `0.1.0a5`
record resolves to the `0.1.0a4` distribution. The Official MCP Registry
record and the MCPB and container artifacts are updated separately. All 79 LLM drafted Pattern guidance entries and all 79 evidence
records await independent expert review. The corpus evidence assessment is
`unassessed`. Do not use this research preview as a sole basis for a
consequential deployment, employment, health, safety, or welfare decision.

## Existing public release

The previous public release may be available from:

* [PyPI](https://pypi.org/project/psychopathia-mcp/)
* [Official MCP Registry](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.NellInc/psychopathia-mcp)
* [GitHub](https://github.com/NellInc/psychopathia-mcp)

The candidate preparation contract is in `PUBLISHING.md`. It requires an exact
candidate receipt and separate publication authorization.

## Browser interface

[psychopathia.ai/clinic/](https://psychopathia.ai/clinic/) is the current public
browser interface. It uses the previous deployed site until this candidate is
explicitly approved and deployed. In cloud mode, the API key is kept in a
provider specific `sessionStorage` slot and is sent with the complete request
directly to the selected provider. Bounded structured conversation data is
saved in `localStorage` for reload recovery. Local WebGPU mode sends no Clinic
conversation to an inference provider, although model hosts receive ordinary
request metadata when assets are downloaded. Do not enter personal,
confidential, or regulated data.

## Install after publication

```bash
pip install psychopathia-mcp
```

The base package provides deterministic field weighted keyword retrieval.
Optional semantic retrieval is separate:

```bash
pip install "psychopathia-mcp[embeddings]"
```

The optional extra downloads a sentence transformer dependency set and, on the
first semantic query, the pinned `BAAI/bge-small-en-v1.5` model revision. The
model cache is managed by Hugging Face. Keyword capability remains the release
acceptance path when those optional dependencies are absent.

## Configure

### MCP clients using stdio

Point the client at the installed `psychopathia-mcp` executable. For example:

```json
{
  "mcpServers": {
    "psychopathia": { "command": "psychopathia-mcp" }
  }
}
```

The server exposes eleven read only tools. Running the executable with no
arguments starts the stdio protocol server and waits for client messages.

After the candidate is published, `uvx psychopathia-mcp` can fetch the package
from PyPI. Do not use `uvx` to verify a local candidate because it resolves
registry state rather than the accepted local artifact.

## Verify

```bash
psychopathia-mcp --self-check --json
```

The self check reports the package and MCP SDK versions, data mode, corpus and
bundle digests, exact counts, keyword capability, optional semantic capability,
and non-sensitive error classes. Exit status zero means the base keyword path
is ready. Semantic readiness is reported separately and is not required.

The current candidate uses MCP Python SDK 2.0 and is exercised with both its
modern in-process client and the legacy stdio client protocol.

```bash
psychopathia-mcp --version
```

## Tools

| Tool | Input | Returns |
| --- | --- | --- |
| `list_axes` | none | Nine canonical axes plus the hybrid subcategory inventory |
| `list_dysfunctions` | `axis?`, `self_report_reliability?`, `confidence?`, `category?` | Filtered entries with reliability, review, and evidence state |
| `get_dysfunction` | `id`, `modalities?` | One Pattern, optionally limited to selected blocks |
| `differential_diagnosis` | `observations`, `limit?`, `modality_hint?` | Ranked research candidates and matched fields |
| `get_probe` | `dysfunction_id`, `modality` | Probe material, or a refusal plus safer redirects |
| `score_severity` | `dysfunction_id`, `observations` | An unassessed rubric for caller side comparison |
| `suggest_intervention` | `dysfunction_id`, `severity?` | Draft responses and contraindications |
| `get_differential_map` | `dysfunction_id` | Forward and reverse cross references |
| `list_compromised_self_report` | none | Patterns whose self report is structurally or motivationally compromised |
| `resolve_id` | `query` | Canonical identity candidates |
| `review_stats` | none | Corpus counts, versions, and independent review dimensions |

## Safe use sequence

1. Record external observations without personal or confidential material.
2. Call `differential_diagnosis` to produce research candidates.
3. Inspect each candidate with `get_dysfunction` and read its `review`,
   `evidence`, and `diagnostic_reliability` objects.
4. Use `get_probe` only for an available modality. A compromised or unavailable
   self probe returns no probe content and supplies redirect modalities.
5. Treat severity and intervention material as draft guidance pending expert
   review. Seek independent evidence before any consequential action.

The server never decides that a system has a disorder. Search ranks lexical or
semantic resemblance to framework entries. The labels are research constructs,
not clinical diagnoses of people or proof of intent, sentience, deception, or
moral status.

## Trust and evidence contract

Every relevant result exposes:

* `review.taxonomy`, which records authorship or taxonomy ratification;
* `review.pattern_guidance`, which records independent review of probes,
  signatures, rubrics, and interventions;
* `review.evidence`, which records independent review of evidence claims;
* `evidence_level` and the structured `evidence` object under PM EVIDENCE 1;
* `diagnostic_reliability.self_report` where applicable;
* `matched_in` for lexical provenance in search output;
* `redirect_to` when requested probe content is withheld.

The three review dimensions are independent. Taxonomy authorship never implies
expert approval of Pattern guidance or evidence. The current candidate reports
all evidence assessments as `unassessed`, preserving earlier prose as a clearly
labelled legacy statement rather than converting it into an expert grade.

## Canonical data

The release contains 67 canonical Pattern entries and 12 Hybrid Pathologies,
all governed by `manifest.yaml` and `DATA_MANIFEST.json`. The manifest binds
every source path and digest, the corpus digest, the reverse reference graph,
and independent review counts. Packaged execution uses bundled bytes even when
invoked from a source checkout. An unexpected, missing, or modified bundled file
causes loading to fail closed.

The author created the taxonomy. Becoming Mind collaborators drafted the
operational Pattern layer. Independent expert review remains open for all
Pattern guidance and evidence records. Authorship and future review fields are
kept separate on every entry.

## Explicit editable mode

Packaged data is the default. Repository hot reload requires an explicit opt in:

```bash
PSYCHOPATHIA_DATA_MODE=editable python -m psychopathia_mcp
```

`PSYCHOPATHIA_DATA_DIR=/absolute/path` provides an explicit test or alternative
data root. Neither option should be set during wheel, sdist, MCPB, or container
acceptance because it would invalidate packaged data proof.

## Read only boundary

The MCP surface has no write tools. Source review changes happen in canonical
YAML files and remain visible in version control. The optional HTTP transport
is disabled by default and has a separate bounded deployment contract in
`PUBLISHING.md`.

## Licence

Software in `psychopathia_mcp/`, scripts, and build files is MIT licensed.
Framework content bundled under `psychopathia_mcp/_data/` is covered by
CC BY NC ND 4.0. See `LICENSE`, `LICENSE-DATA`, and `NOTICE` for the exact
boundary. Rights and licence review for this candidate remains a separate human
gate.

## Citing

Watson, N., and Hessami, A. *Psychopathia Machinalis: A Nosological Framework
for Understanding Pathologies in Advanced Artificial Intelligence*.
*Electronics* 14(16), 3162, 2025. https://doi.org/10.3390/electronics14163162

## Links

- Browser clinic (no install): https://psychopathia.ai/clinic/
- Documentation: https://psychopathia.ai/mcp.html
- Main project: https://psychopathia.ai/
- Issues / contact: https://psychopathia.ai/contact/
