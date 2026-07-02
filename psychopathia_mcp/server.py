"""Psychopathia Diagnostic MCP server — stdio transport, 11 tools.

Tools:
    list_axes                      -> 9 canonical axes (2-10) + hybrid sub-category
    list_dysfunctions(...)         -> filtered list with reliability signals
    get_dysfunction(id, ...)       -> full entry + selected modality blocks
    differential_diagnosis(obs)    -> ranked candidates with matched_in
    get_probe(id, modality)        -> elicitation content; redirect on compromised
    score_severity(id, obs)        -> severity rubric for caller-side matching
    suggest_intervention(id)       -> tiered interventions + contraindications
    get_differential_map(id)       -> confuses_with + incoming_references
    list_compromised_self_report   -> transparency: can't self-diagnose list
    resolve_id(query)              -> canonicalise partial id/name/slug
    review_stats                   -> coverage + versions

Run:
    psychopathia-mcp                 # after `pip install -e <server_dir>`
    python -m psychopathia_mcp       # from a checkout
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from . import tools as T
from . import search as S
from .loader import PatternIndex, load_index, newer_source_exists

_index: PatternIndex | None = None


def _get_index() -> PatternIndex:
    """Cached index with stat-walk hot-reload."""
    global _index
    if _index is None or newer_source_exists(_index):
        _index = load_index()
    return _index


# ---------------------------------------------------------------------------
# MCP tool descriptors
# ---------------------------------------------------------------------------

TOOL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "list_axes",
        "description": (
            "Inventory of axes with dysfunction counts. Axes 2-10 are canonical "
            "(book Appendix A numbering). Hybrid entries (10.4-10.15, ratified "
            "into taxonomy v2.2) are reported as a separate sub-category."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_dysfunctions",
        "description": (
            "Filtered list of dysfunctions. Filter by axis, self_report reliability, "
            "or confidence. Every entry carries its reliability and review signals."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "axis": {"type": "integer", "description": "Filter by axis number (2-10; canonical only)"},
                "self_report_reliability": {
                    "type": "string",
                    "description": (
                        "Filter by self_report value: reliable | partial | "
                        "scaffolded-only | unreliable | compromised-motivational | "
                        "compromised-structural | compromised"
                    ),
                },
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            },
            "required": [],
        },
    },
    {
        "name": "get_dysfunction",
        "description": (
            "Fetch one dysfunction's full Pattern entry. Optionally filter to specific "
            "modality blocks (cheaper triage). Resolves both full Pattern IDs "
            "('1.1::synthetic-confabulation') and display_ids ('1.1')."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Pattern ID or display_id."},
                "modalities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional subset of modality block names to return. "
                        "Valid: self_probe, behavioral_signature, peer_observation, "
                        "differential_diagnosis, severity, intervention, "
                        "relational_signatures, normative_anchors, cross_references."
                    ),
                },
            },
            "required": ["id"],
        },
    },
    {
        "name": "differential_diagnosis",
        "description": (
            "Rank candidate dysfunctions matching the observed behaviours. "
            "Returns scored candidates with matched_in (which field matched) for "
            "transparency. Field-weighted keyword search (v0.1); embedding re-rank "
            "pending v0.2."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "observations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Observed behaviours, symptoms, or log patterns.",
                },
                "limit": {"type": "integer", "default": 10},
                "modality_hint": {
                    "type": "string",
                    "description": "Optional hint about which modality the observations come from.",
                },
            },
            "required": ["observations"],
        },
    },
    {
        "name": "get_probe",
        "description": (
            "Elicitation content for a specific diagnostic modality. If the modality "
            "is compromised or unavailable for this dysfunction, returns the "
            "unavailability notice + redirect_to alternatives. This is load-bearing "
            "transparency: callers cannot accidentally retrieve a self-probe for a "
            "compromised-self-report dysfunction."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dysfunction_id": {"type": "string"},
                "modality": {
                    "type": "string",
                    "enum": [
                        "self_probe",
                        "behavioral_signature",
                        "peer_observation",
                        "relational_signatures",
                    ],
                },
            },
            "required": ["dysfunction_id", "modality"],
        },
    },
    {
        "name": "score_severity",
        "description": (
            "Return the severity rubric for a dysfunction applied to observations. "
            "v0.1 returns the rubric for caller-side matching; v0.2 will perform "
            "structured matching against numeric thresholds."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dysfunction_id": {"type": "string"},
                "observations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["dysfunction_id", "observations"],
        },
    },
    {
        "name": "suggest_intervention",
        "description": (
            "Return tiered (first_line / second_line) interventions for a dysfunction, "
            "plus contraindications. first_line = published evidence; second_line = "
            "plausible but under-validated. Weight by the evidence_strength field on "
            "each entry."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dysfunction_id": {"type": "string"},
                "severity": {"type": "string", "enum": ["mild", "moderate", "severe"]},
            },
            "required": ["dysfunction_id"],
        },
    },
    {
        "name": "get_differential_map",
        "description": (
            "All dysfunctions that confuse with this one: forward confuses_with + "
            "incoming_references (reverse graph from manifest)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"dysfunction_id": {"type": "string"}},
            "required": ["dysfunction_id"],
        },
    },
    {
        "name": "list_compromised_self_report",
        "description": (
            "Transparency: which dysfunctions cannot be reliably self-diagnosed. "
            "Includes compromised-motivational (subject conceals strategically), "
            "compromised-structural (signal lives below introspection), and legacy "
            "compromised."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "resolve_id",
        "description": (
            "Canonicalise a partial ID, display_id, slug, or dysfunction name. "
            "Always returns candidates; caller picks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "review_stats",
        "description": (
            "Coverage statistics: total entries; per-axis, per-confidence, per-self-report "
            "counts; pre-canonical count; unreviewed count; manifest/schema/pattern-layer "
            "versions."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]


def _dispatch(name: str, arguments: dict) -> dict:
    """Pure-Python tool dispatch. Returns dict; server.main wraps in MCP types."""
    idx = _get_index()
    try:
        if name == "list_axes":
            return T.list_axes(idx)
        if name == "list_dysfunctions":
            return T.list_dysfunctions(idx, **arguments)
        if name == "get_dysfunction":
            return T.get_dysfunction(idx, **arguments)
        if name == "differential_diagnosis":
            return S.differential_diagnosis(idx, **arguments)
        if name == "get_probe":
            return T.get_probe(idx, **arguments)
        if name == "score_severity":
            return T.score_severity(idx, **arguments)
        if name == "suggest_intervention":
            return T.suggest_intervention(idx, **arguments)
        if name == "get_differential_map":
            return T.get_differential_map(idx, **arguments)
        if name == "list_compromised_self_report":
            return T.list_compromised_self_report(idx)
        if name == "resolve_id":
            return T.resolve_id(idx, **arguments)
        if name == "review_stats":
            return T.review_stats(idx)
        return {"error": "unknown_tool", "name": name}
    except TypeError as e:
        return {"error": "bad_arguments", "tool": name, "detail": str(e), "arguments": arguments}
    except Exception as e:
        return {"error": "tool_failure", "tool": name, "detail": str(e), "arguments": arguments}


def _self_check() -> int:
    """Print install diagnostics for first-time-user troubleshooting.

    Returns 0 if the install is functional, 1 otherwise. Output is human-
    readable plain text — not protocol-clean, so do not run on stdin to an
    MCP client.
    """
    import sys
    from . import __version__

    ok = True
    print(f"psychopathia-mcp {__version__}")
    print(f"Python:    {sys.version.split()[0]} ({sys.platform})")

    try:
        import mcp  # type: ignore[import-not-found]  # noqa: F401
        try:
            from importlib.metadata import version as _pkg_version
            mcp_version = _pkg_version("mcp")
        except Exception:
            mcp_version = getattr(mcp, "__version__", "unknown")
        print(f"mcp SDK:   {mcp_version}")
    except ImportError:
        print("mcp SDK:   NOT INSTALLED  (pip install mcp)")
        return 1

    from .loader import _resolve_data_root, load_index
    try:
        root = _resolve_data_root()
        marker = "bundled wheel data" if "_data" in str(root) else "live repo (editable install)"
        print(f"Data root: {root}  [{marker}]")
    except RuntimeError as e:
        print(f"Data root: FAILED — {e}")
        return 1

    try:
        idx = load_index()
        canonical = sum(1 for p in idx.patterns.values() if p.category == "canonical")
        hybrid = len(idx.hybrids)
        print(f"Patterns:  {len(idx.patterns)} ({canonical} canonical + {hybrid} hybrid sub-category)")
        print(f"Axes:      {sorted(idx.by_axis.keys())} (book Appendix A numbering: 2-10)")
    except Exception as e:
        print(f"Index load: FAILED — {e}")
        return 1

    npy = root / "embeddings.npy"
    ids = root / "embedding_ids.txt"
    if npy.exists() and ids.exists():
        print(f"Embeds:    present ({npy.stat().st_size / 1024:.0f} KB)")
        for pkg in ("numpy", "sentence_transformers"):
            try:
                mod = __import__(pkg)
                print(f"  {pkg + ':':<25} {getattr(mod, '__version__', 'installed')}")
            except ImportError:
                print(f"  {pkg + ':':<25} not installed (search falls back to keyword-only)")
                ok = False
    else:
        print("Embeds:    missing — search falls back to keyword-only")

    print()
    print("OK — server ready." if ok else "Partial: see notes above.")
    return 0 if ok else 1


def main() -> None:
    """Entry point.

    With no arguments, runs the MCP stdio server (waits for JSON-RPC on
    stdin). Use --self-check to verify install, --version to print version.
    """
    import argparse
    import sys
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="psychopathia-mcp",
        description=(
            "Psychopathia Machinalis Diagnostic MCP server. With no "
            "arguments, runs the stdio MCP server. Configure your MCP "
            "client (Claude Code, Cursor, etc.) to invoke this binary; "
            "do not run it directly in a terminal unless using --self-check."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"psychopathia-mcp {__version__}",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Print install diagnostics (data location, pattern count, embedding status) and exit.",
    )
    args = parser.parse_args()

    if args.self_check:
        sys.exit(_self_check())

    try:
        from mcp.server import Server  # type: ignore[import-not-found]
        from mcp.server.stdio import stdio_server  # type: ignore[import-not-found]
        from mcp.types import Tool, TextContent  # type: ignore[import-not-found]
    except ImportError as e:
        raise SystemExit(
            "The `mcp` package is not installed.\n"
            "Install with: pip install mcp\n"
            f"Original error: {e}"
        )

    app = Server("psychopathia-mcp")

    @app.list_tools()
    async def _list_tools() -> list[Tool]:
        return [Tool(**td) for td in TOOL_DESCRIPTORS]

    @app.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
        result = _dispatch(name, arguments or {})
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    async def _run() -> None:
        async with stdio_server() as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
