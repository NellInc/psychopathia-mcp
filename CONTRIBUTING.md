# Working in `psychopathia-mcp` — read this first

**This repository is a published mirror, not the source of truth.**

`psychopathia-mcp` is the public, installable home of the MCP server for the
*Psychopathia Machinalis* diagnostic framework. Its contents are **generated and
mirrored** from a private monorepo. Anything you edit *here* will be **silently
overwritten** the next time the maintainer runs the release sync
(`scripts/sync-to-public.sh`).

## If you want to change something

- **Bug reports & feature requests:** open a GitHub issue here — that's the right
  place and it's watched.
- **Code / data / docs changes:** these are authored upstream in the private
  monorepo (`research/mcp/server/`) and mirrored out. A pull request against this
  repo can't be merged in the normal way (the sync would clobber it), but it is
  very welcome as a **proposal** the maintainer can apply upstream — describe the
  intent clearly and it will be carried across.

## Don't hand-edit generated content

- `psychopathia_mcp/_data/` — the diagnostic corpus (79 pattern entries plus tool
  data) is generated from the canonical *Psychopathia Machinalis* nosology upstream.
  Editing the YAML here changes nothing durable.

## Where it's published

- **PyPI:** `psychopathia-mcp` — run with `uvx psychopathia-mcp` (or `pipx` / `pip`).
- **Official MCP Registry:** `io.github.NellInc/psychopathia-mcp` (see `server.json`).
- Rolling out across mcp.directory, mcpservers.org, PulseMCP, mcp.so, and Glama.

The registry namespace is owner-based (`io.github.NellInc/…`), so it stays valid
independent of this repo's name — the listing points at the PyPI package, not a
clone of this repo.

## Using the server

See [`README.md`](README.md) for install/config and the 11 diagnostic tools
(`differential_diagnosis`, `list_compromised_self_report`, …). The browser clinic
at <https://psychopathia.ai/clinic/> runs the same corpus with nothing to install.

---

*Maintainer: Nell Watson · Framework & questions: <https://psychopathia.ai>*
