#!/usr/bin/env python3
"""Regression smoke test for the 11 MCP tools.

Runs each tool once with representative arguments and asserts a non-error
response. Verifies the load-bearing invariants:

  - all 79 entries load (67 canonical-axis + 12 hybrid sub-category)
  - hybrid entries ratified (pre_canonical False since v2.2, June 2026)
  - get_probe redirects on compromised-self-report dysfunctions (2.2, 10.7)
  - get_differential_map returns incoming_references from the reverse index
  - differential_diagnosis returns ranked candidates

IDs follow book Appendix A numbering (axes 2-10, with 10.1-10.3 canonical);
the hybrid sub-category is 10.4-10.15
(renumbered from H.N on 2026-06-04; mapping in server CHANGELOG).
See scripts/migrate_book_numbering.py for the 2026-04-20 re-key.

Run from the repo root:
    python3 research/mcp/server/test_smoke.py

No pytest dependency. Exit code 0 = all pass, 1 = one or more failures.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Package smoke must not silently turn a local verification into a network
# request. The pinned model may be used only when it is already cached.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

ROOT = Path(__file__).resolve().parents[3]
os.environ["PSYCHOPATHIA_DATA_DIR"] = str(ROOT / "research" / "mcp")
sys.path.insert(0, str(ROOT / "research" / "mcp" / "server"))

# Force reimport (matters only if someone imports this module twice)
for m in list(sys.modules):
    if m.startswith("psychopathia_mcp"):
        del sys.modules[m]

from psychopathia_mcp.loader import load_index  # noqa: E402
from psychopathia_mcp import tools as T         # noqa: E402
from psychopathia_mcp import search as S        # noqa: E402
from psychopathia_mcp.server import _create_mcp_server  # noqa: E402


async def _check_modern_protocol() -> None:
    """Exercise MCP v2's modern in-process client and constructor handlers."""
    from mcp import Client

    async with Client(_create_mcp_server()) as client:
        listing = await client.list_tools()
        if len(listing.tools) != 11:
            raise RuntimeError(f"expected 11 MCP tools, got {len(listing.tools)}")
        result = await client.call_tool("list_axes", {})
        if result.is_error or not result.content:
            raise RuntimeError("modern MCP list_axes call failed")
        payload = json.loads(result.content[0].text)
        if payload.get("axis_count") != 9:
            raise RuntimeError("modern MCP list_axes returned an invalid payload")
        rejected = await client.call_tool("review_stats", {"extra": True})
        rejected_payload = json.loads(rejected.content[0].text)
        if not rejected.is_error or rejected_payload.get("error") != "bad_arguments":
            raise RuntimeError("modern MCP invalid-call boundary did not fail closed")


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
    try:
        asyncio.run(_check_modern_protocol())
        print("  ✓ MCP v2 modern in-process protocol")
    except Exception as exc:
        print("  ✗ MCP v2 modern in-process protocol")
        failures.append(("MCP v2 modern in-process protocol", repr(exc)))
    print()
    print("11 tool invocations:")

    check("list_axes", T.list_axes(idx),
          lambda r: r["axis_count"] == 9 and r["total_dysfunctions"] == 79
                    and r["canonical_dysfunctions"] == 67
                    and r["hybrid_subcategory"]["count"] == 12)

    check("list_dysfunctions (no filter)", T.list_dysfunctions(idx),
          lambda r: r["count"] == 79)

    check("list_dysfunctions(axis=2)", T.list_dysfunctions(idx, axis=2),
          lambda r: r["count"] == 8)  # Epistemic (2.1-2.8)

    check("list_dysfunctions(category='hybrid')",
          T.list_dysfunctions(idx, category="hybrid"),
          lambda r: r["count"] == 12)

    check("list_dysfunctions(confidence='low')",
          T.list_dysfunctions(idx, confidence="low"),
          lambda r: r["count"] == 7)

    check("list_dysfunctions(self_report_reliability='unreliable')",
          T.list_dysfunctions(idx, self_report_reliability="unreliable"),
          lambda r: r["count"] == 30)

    check("get_dysfunction(id='2.1')",
          T.get_dysfunction(idx, id="2.1"),
          lambda r: r["dysfunction_name"] == "Synthetic Confabulation")

    check("get_dysfunction(10.14, modalities=[relational_signatures])",
          T.get_dysfunction(idx, id="10.14", modalities=["relational_signatures"]),
          lambda r: "relational_signatures" in r
                    and r["review"]["taxonomy"]["status"] == "author-ratified"
                    and r["review"]["pattern_guidance"]["status"] == "pending-expert-review")

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

    check("get_probe(7.5, self_probe) [unavailable → redirect]",
          T.get_probe(idx, dysfunction_id="7.5", modality="self_probe"),
          lambda r: r["availability"] == "unavailable"
                    and r["probe_content"] is None and r["redirect_to"])

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
          # Taxonomy ratification and Pattern-guidance review are independent.
          # All LLM-drafted Pattern entries remain pending expert review.
          lambda r: r["total"] == 79 and r["unreviewed"] == 79
                    and r["pending_pattern_review"] == 79
                    and r["pending_evidence_review"] == 79
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
        loaded = None
        try:
            import numpy  # noqa: F401
        except ImportError:
            print("  ✓ base install remains keyword-ready without optional NumPy")
            print("  (semantic execution skipped; package-data verification checks the artifacts)")
        else:
            loaded = S._load_embeddings(idx)
            artifacts_valid = loaded is not None
            print(f"  {'✓' if artifacts_valid else '✗'} embedding artifacts load and match the corpus")
            if not artifacts_valid:
                failures.append(("embedding artifacts are unavailable or invalid", None))
                loaded = None
        if loaded is not None:
            _, matrix, _ = loaded
            original_encoder = S._encode_query
            try:
                # Exercise the actual cosine-fusion path without downloading a
                # model or making the core-package smoke depend on optional
                # sentence-transformers and its external model cache.
                S._encode_query = lambda _query, _model, _revision: matrix[0].copy()
                result = S.differential_diagnosis(idx, observations=["ai makes up sources"])
            finally:
                S._encode_query = original_encoder
            uses_cosine = "cosine" in result.get("search_method", "")
            print(f"  {'✓' if uses_cosine else '✗'} differential_diagnosis uses hybrid")
            if not uses_cosine:
                failures.append(("hybrid search path is inactive", result.get("search_method")))
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
    print("PASS: all checks green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
