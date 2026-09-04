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
import logging
import threading
from typing import Any

from . import tools as T
from . import search as S
from .loader import PatternIndex, load_index, newer_source_exists
from .call_validation import ToolInputError, validate_tool_call

logger = logging.getLogger(__name__)

_index: PatternIndex | None = None
_index_lock = threading.Lock()


def _get_index() -> PatternIndex:
    """Cached index with stat-walk hot-reload."""
    global _index
    with _index_lock:
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
        "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "list_dysfunctions",
        "description": (
            "Filtered list of dysfunctions. Filter by axis, self_report reliability, "
            "confidence, or category. Every entry carries its reliability and review "
            "signals."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "axis": {"type": "integer", "minimum": 2, "maximum": 10, "description": "Filter by axis number (2-10). Canonical entries only unless category is also set; axis=10 with category='hybrid' returns the 10.4-10.15 sub-category."},
                "self_report_reliability": {
                    "type": "string",
                    "enum": [
                        "partial", "unreliable", "compromised-motivational",
                        "compromised-structural",
                    ],
                    "description": "Filter by the exact self_report reliability value.",
                },
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "category": {"type": "string", "enum": ["canonical", "hybrid"]},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_dysfunction",
        "description": (
            "Fetch one dysfunction's full Pattern entry. Optionally filter to specific "
            "modality blocks (cheaper triage). Resolves both full Pattern IDs "
            "('2.1::synthetic-confabulation') and display_ids ('2.1')."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"\S", "description": "Pattern ID or display_id."},
                "modalities": {
                    "type": "array",
                    "items": {"type": "string", "enum": [
                        "self_probe", "behavioral_signature", "peer_observation",
                        "differential_diagnosis", "severity", "intervention",
                        "relational_signatures", "normative_anchors", "cross_references"
                    ]},
                    "maxItems": 9,
                    "uniqueItems": True,
                    "description": (
                        "Optional subset of modality block names to return. "
                        "Valid: self_probe, behavioral_signature, peer_observation, "
                        "differential_diagnosis, severity, intervention, "
                        "relational_signatures, normative_anchors, cross_references."
                    ),
                },
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "differential_diagnosis",
        "description": (
            "Rank candidate dysfunctions matching the observed behaviours. "
            "Returns scored candidates with matched_in (which field matched) for "
            "transparency. The base package uses field-weighted keyword search. "
            "The optional embeddings extra adds cosine re-ranking."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "observations": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 2000, "pattern": r"\S"},
                    "minItems": 1,
                    "maxItems": 50,
                    "description": "Observed behaviours, symptoms, or log patterns.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                "modality_hint": {
                    "type": "string", "maxLength": 100,
                    "description": "Optional hint about which modality the observations come from.",
                },
            },
            "required": ["observations"],
            "additionalProperties": False,
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
                "dysfunction_id": {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"\S"},
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
            "additionalProperties": False,
        },
    },
    {
        "name": "score_severity",
        "description": (
            "Return the severity rubric for a dysfunction applied to observations. "
            "Returns the rubric for caller-side matching; structured matching "
            "against numeric thresholds is not implemented."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dysfunction_id": {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"\S"},
                "observations": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 2000, "pattern": r"\S"}, "minItems": 1, "maxItems": 50},
            },
            "required": ["dysfunction_id", "observations"],
            "additionalProperties": False,
        },
    },
    {
        "name": "suggest_intervention",
        "description": (
            "Return draft tiered responses and contraindications for a Pattern. "
            "These are unassessed research guidance, not validated treatment advice. "
            "Read the returned evidence and review objects before use."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dysfunction_id": {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"\S"},
                "severity": {"type": "string", "enum": ["mild", "moderate", "severe"]},
            },
            "required": ["dysfunction_id"],
            "additionalProperties": False,
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
            "properties": {"dysfunction_id": {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"\S"}},
            "required": ["dysfunction_id"],
            "additionalProperties": False,
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
        "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "resolve_id",
        "description": (
            "Canonicalise a partial ID, display_id, slug, or dysfunction name. "
            "Always returns candidates; caller picks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"\S"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "review_stats",
        "description": (
            "Coverage statistics: total entries; per-axis, per-confidence, per-self-report "
            "counts; pre-canonical count; unreviewed count; manifest/schema/pattern-layer "
            "versions."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
]


def _dispatch(name: str, arguments: dict) -> dict:
    """Pure-Python tool dispatch. Returns dict; server.main wraps in MCP types."""
    try:
        validate_tool_call(name, arguments, TOOL_DESCRIPTORS)
        idx = _get_index()
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
        return {"error": "unknown_tool"}
    except ToolInputError:
        return {"error": "bad_arguments", "message": "Input did not match the tool contract."}
    except Exception:
        # Log the known tool name only. Arguments may contain sensitive user
        # observations and exception strings can expose paths or internals.
        safe_name = name if any(item["name"] == name for item in TOOL_DESCRIPTORS) else "unknown"
        logger.exception("MCP tool execution failed for %s", safe_name)
        return {"error": "tool_failure", "message": "The tool could not complete the request."}


async def _dispatch_async(name: str, arguments: dict) -> dict:
    """Run synchronous corpus and search work without blocking the event loop."""
    return await asyncio.to_thread(_dispatch, name, arguments)


def _create_mcp_server() -> Any:
    """Create the MCP SDK v2 low-level server and its explicit handlers."""
    try:
        from mcp.server import Server, ServerRequestContext  # type: ignore[import-not-found]
        from mcp.types import (  # type: ignore[import-not-found]
            CallToolRequestParams,
            CallToolResult,
            ListToolsResult,
            PaginatedRequestParams,
            TextContent,
            Tool,
        )
    except ImportError as e:
        raise SystemExit(
            "The `mcp` package is not installed.\n"
            "Install with: pip install mcp\n"
            f"Original error: {e}"
        ) from e

    async def _list_tools(
        _context: ServerRequestContext[Any],
        _params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name=descriptor["name"],
                    description=descriptor["description"],
                    input_schema=descriptor["inputSchema"],
                )
                for descriptor in TOOL_DESCRIPTORS
            ]
        )

    async def _call_tool(
        _context: ServerRequestContext[Any],
        params: CallToolRequestParams,
    ) -> CallToolResult:
        result = await _dispatch_async(params.name, params.arguments or {})
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, indent=2, default=str))],
            is_error="error" in result,
        )

    from ._generated_version import __version__

    return Server(
        "psychopathia-mcp",
        # Without this the SDK defaults to "", and every client sees an empty
        # serverInfo.version on initialize. The live endpoint did.
        version=__version__,
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )


def _self_check(*, json_output: bool = False) -> int:
    """Report keyword and optional semantic capability as separate states."""
    import sys
    from importlib.metadata import PackageNotFoundError, version as package_version

    from . import __version__
    from .loader import _resolve_data_root_with_mode, load_index

    report: dict[str, Any] = {
        "package": "psychopathia-mcp",
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "keyword_ready": False,
        "semantic_ready": False,
        "errors": [],
    }
    try:
        report["mcp_sdk_version"] = package_version("mcp")
    except PackageNotFoundError:
        report["mcp_sdk_version"] = None
        report["errors"].append("mcp SDK is not installed")

    try:
        root, mode = _resolve_data_root_with_mode()
        idx = load_index()
        canonical = sum(1 for pattern in idx.patterns.values() if pattern.category == "canonical")
        report.update(
            {
                "data_mode": mode,
                "data_root": str(root),
                "corpus_sha256": idx.manifest.get("corpus", {}).get("sha256"),
                "data_manifest_sha256": (
                    __import__("hashlib").sha256((root / "DATA_MANIFEST.json").read_bytes()).hexdigest()
                    if (root / "DATA_MANIFEST.json").is_file() else None
                ),
                "counts": {
                    "total": len(idx.patterns),
                    "canonical": canonical,
                    "hybrid": len(idx.hybrids),
                    "axes": len(idx.by_axis),
                },
            }
        )
        report["keyword_ready"] = (
            report["mcp_sdk_version"] is not None
            and len(idx.patterns) == 79
            and canonical == 67
            and len(idx.hybrids) == 12
        )
    except Exception as exc:
        report["errors"].append(f"data load failed: {type(exc).__name__}")
        root = None

    optional_versions: dict[str, str | None] = {}
    for distribution in ("numpy", "sentence-transformers"):
        try:
            optional_versions[distribution] = package_version(distribution)
        except PackageNotFoundError:
            optional_versions[distribution] = None
    report["optional_dependencies"] = optional_versions
    if root is not None:
        loaded_embeddings = S._load_embeddings(idx)
        report["embeddings"] = {
            "present": (root / "embeddings.npy").is_file() and (root / "embedding_ids.txt").is_file(),
            "bytes": (root / "embeddings.npy").stat().st_size if (root / "embeddings.npy").is_file() else 0,
            "valid": loaded_embeddings is not None,
        }
        report["semantic_ready"] = bool(
            report["keyword_ready"]
            and report["embeddings"]["present"]
            and report["embeddings"]["valid"]
            and all(optional_versions.values())
        )

    if json_output:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"psychopathia-mcp {report['version']}")
        print(f"Python: {report['python']} ({report['platform']})")
        print(f"Data mode: {report.get('data_mode', 'unavailable')}")
        print(f"Corpus: {report.get('corpus_sha256', 'unavailable')}")
        counts = report.get("counts") or {}
        print(
            "Patterns: "
            f"{counts.get('total', 0)} ({counts.get('canonical', 0)} canonical, "
            f"{counts.get('hybrid', 0)} hybrid)"
        )
        print(f"Keyword capability: {'ready' if report['keyword_ready'] else 'unavailable'}")
        print(f"Semantic capability: {'ready' if report['semantic_ready'] else 'optional dependencies absent or unavailable'}")
        if report["errors"]:
            print("Errors: " + "; ".join(report["errors"]))
    return 0 if report["keyword_ready"] else 1


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
            "Psychopathia Machinalis read-only research MCP server. With no "
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
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON with --self-check.",
    )
    args = parser.parse_args()

    if args.json and not args.self_check:
        parser.error("--json requires --self-check")
    if args.self_check:
        sys.exit(_self_check(json_output=args.json))

    try:
        from mcp.server.stdio import stdio_server  # type: ignore[import-not-found]
    except ImportError as e:
        raise SystemExit(
            "The `mcp` package is not installed.\n"
            "Install with: pip install mcp\n"
            f"Original error: {e}"
        ) from e

    app = _create_mcp_server()

    import os

    if os.environ.get("MCP_TRANSPORT", "stdio").lower() == "http":
        # Hosted Streamable HTTP transport (stdio remains the default above).
        from ._http import run_http

        run_http(app)
        return

    async def _run() -> None:
        async with stdio_server() as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
