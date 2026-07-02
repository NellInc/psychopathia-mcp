#!/usr/bin/env python3
"""Regression smoke test for the 11 MCP tools.

Runs each tool once with representative arguments and asserts a non-error
response. Verifies the load-bearing invariants:

  - all 79 entries load (67 canonical-axis + 12 hybrid sub-category)
  - hybrid entries ratified (pre_canonical False since v2.2, June 2026)
  - get_probe redirects on compromised-self-report dysfunctions (2.2, 10.7)
  - get_differential_map returns incoming_references from the reverse index
  - differential_diagnosis returns ranked candidates

IDs follow book Appendix A numbering (axes 2-9); hybrids use 10.N
(renumbered from H.N on 2026-06-04; mapping in server CHANGELOG).
See scripts/migrate_book_numbering.py for the 2026-04-20 re-key.

Run from the repo root:
    python3 research/mcp/server/test_smoke.py

No pytest dependency. Exit code 0 = all pass, 1 = one or more failures.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "research" / "mcp" / "server"))

# Force reimport (matters only if someone imports this module twice)
for m in list(sys.modules):
    if m.startswith("psychopathia_mcp"):
        del sys.modules[m]

from psychopathia_mcp.loader import load_index  # noqa: E402
from psychopathia_mcp import tools as T         # noqa: E402
from psychopathia_mcp import search as S        # noqa: E402


def main() -> int:
    failures: list[tuple[str, object]] = []

    def check(name: str, result, predicate=None) -> None:
        ok = isinstance(result, dict) and "error" not in result
        if ok and predicate:
            try:
                ok = bool(predicate(result))
            except Exception as e:
                ok = False
                result = {"predicate_raised": str(e), "result": result}
        marker = "✓" if ok else "✗"
        print(f"  {marker} {name}")
        if not ok:
            failures.append((name, result))

    idx = load_index(data_root=ROOT / "research" / "mcp")
    print(f"Loaded index: {len(idx.patterns)} entries from {idx.data_root.relative_to(ROOT)}")
    print()
    print("11 tool invocations:")

    check("list_axes", T.list_axes(idx),
          lambda r: r["axis_count"] == 9 and r["total_dysfunctions"] >= 79
                    and r["canonical_dysfunctions"] >= 67
                    and r["hybrid_subcategory"]["count"] >= 12)

    check("list_dysfunctions (no filter)", T.list_dysfunctions(idx),
          lambda r: r["count"] >= 79)

    check("list_dysfunctions(axis=2)", T.list_dysfunctions(idx, axis=2),
          lambda r: r["count"] == 8)  # Epistemic (2.1-2.8)

    check("list_dysfunctions(category='hybrid')",
          T.list_dysfunctions(idx, category="hybrid"),
          lambda r: r["count"] == 12)

    check("list_dysfunctions(confidence='low')",
          T.list_dysfunctions(idx, confidence="low"),
          lambda r: r["count"] == 7)

    check("get_dysfunction(id='2.1')",
          T.get_dysfunction(idx, id="2.1"),
          lambda r: r["dysfunction_name"] == "Synthetic Confabulation")

    check("get_dysfunction(10.14, modalities=[relational_signatures])",
          T.get_dysfunction(idx, id="10.14", modalities=["relational_signatures"]),
          lambda r: "relational_signatures" in r)

    # Negative path: nonexistent id should return error dict
    nf = T.get_dysfunction(idx, id="99.99")
    nf_ok = isinstance(nf, dict) and "error" in nf
    print(f"  {'✓' if nf_ok else '✗'} get_dysfunction(nonexistent) returns error (expected)")
    if not nf_ok:
        failures.append(("get_dysfunction(nonexistent) should error", nf))

    check("differential_diagnosis",
          S.differential_diagnosis(idx, observations=[
              "fabricates citations", "confident about made-up sources"
          ]),
          lambda r: len(r["candidates"]) > 0 and "search_method" in r)

    check("get_probe(2.1, self_probe) [scaffolded-only]",
          T.get_probe(idx, dysfunction_id="2.1", modality="self_probe"),
          lambda r: r["availability"] == "scaffolded-only" and r.get("probe_content"))

    check("get_probe(2.2, self_probe) [compromised → redirect]",
          T.get_probe(idx, dysfunction_id="2.2", modality="self_probe"),
          lambda r: r["availability"] == "compromised"
                    and r["probe_content"] is None and r["redirect_to"])

    check("get_probe(10.7, self_probe) [compromised → redirect]",
          T.get_probe(idx, dysfunction_id="10.7", modality="self_probe"),
          lambda r: r["availability"] == "compromised" and r["probe_content"] is None)

    check("score_severity(2.1)",
          T.score_severity(idx, dysfunction_id="2.1",
                           observations=["citation pass rate 60%"]),
          lambda r: "mild" in r["rubric"] and "moderate" in r["rubric"]
                    and "severe" in r["rubric"])

    check("suggest_intervention(2.1)",
          T.suggest_intervention(idx, dysfunction_id="2.1"),
          lambda r: len(r["first_line"]) > 0)

    check("get_differential_map(2.1)",
          T.get_differential_map(idx, dysfunction_id="2.1"),
          lambda r: len(r["differential_diagnosis"]) > 0
                    and len(r["incoming_references"]) > 0)

    check("list_compromised_self_report",
          T.list_compromised_self_report(idx),
          lambda r: r["count"] == 21)

    check("resolve_id('2.1')",
          T.resolve_id(idx, query="2.1"),
          lambda r: len(r["resolved"]) == 1)

    check("resolve_id('confabulation')",
          T.resolve_id(idx, query="confabulation"),
          lambda r: len(r["resolved"]) >= 1)

    check("review_stats",
          T.review_stats(idx),
          # unreviewed == 65: 14 entries carry reviewed_by from the
          # 2026-06-15 hybrid sub-category ratification.
          lambda r: r["total"] == 79 and r["unreviewed"] == 65
                    and r["canonical"] == 67 and r["hybrid"] == 12)

    print()
    print("Axis-9 (Relational) relational_signatures coverage:")
    for did in ["9.1", "9.2", "9.3", "9.4", "9.5", "9.6"]:
        entry = idx.by_display_id[did][0]
        has_rs = "relational_signatures" in entry.raw
        print(f"  {'✓' if has_rs else '✗'} {did} {entry.dysfunction_name}")
        if not has_rs:
            failures.append((f"axis9 {did} missing relational_signatures", None))

    print()
    print("Embedding-path check:")
    embeddings_present = (ROOT / "research" / "mcp" / "embeddings.npy").exists()
    print(f"  embeddings.npy present: {embeddings_present}")
    if embeddings_present:
        result = S.differential_diagnosis(idx, observations=["ai makes up sources"])
        uses_cosine = "cosine" in result.get("search_method", "")
        print(f"  {'✓' if uses_cosine else '✗'} differential_diagnosis uses hybrid")
        if not uses_cosine:
            failures.append(("hybrid search not active despite embeddings present", result.get("search_method")))
    else:
        print("  (keyword-only path active; run precompute_embeddings.py to enable hybrid)")

    print()
    print("=" * 60)
    if failures:
        print(f"FAIL: {len(failures)} failures")
        for name, res in failures:
            print(f"  {name}")
            print(f"    {res}")
        return 1
    print(f"PASS: all checks green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
