"""Tool implementations — pure Python, no MCP types.

Each tool takes the PatternIndex + kwargs and returns a JSON-serializable
dict. server.py wraps these with MCP protocol handlers.
"""
from __future__ import annotations

from typing import Optional

from .loader import PatternIndex, PatternEntry

_COMPROMISED_VALUES = {
    "compromised",
    "compromised-motivational",
    "compromised-structural",
}

_VALID_PROBE_MODALITIES = {
    "self_probe",
    "behavioral_signature",
    "peer_observation",
    "relational_signatures",
}


def list_axes(idx: PatternIndex) -> dict:
    """Inventory of canonical axes (2..10) with counts. Hybrids reported separately."""
    axes: dict[int, dict] = {}
    for entry in idx.patterns.values():
        if entry.axis_number is None or entry.category == "hybrid":
            continue  # hybrids are reported separately, not double-counted in axes
        n = entry.axis_number
        if n not in axes:
            axes[n] = {
                "axis_number": n,
                "axis_name": entry.axis_name,
                "dysfunction_count": 0,
            }
        axes[n]["dysfunction_count"] += 1

    hybrid_count = len(idx.hybrids)
    hybrid_by_subject: dict[str, int] = {}
    for h in idx.hybrids:
        st = h.raw.get("subject_type") or "unknown"
        hybrid_by_subject[st] = hybrid_by_subject.get(st, 0) + 1

    return {
        "axis_count": len(axes),
        "total_dysfunctions": sum(a["dysfunction_count"] for a in axes.values()) + hybrid_count,
        "canonical_dysfunctions": sum(a["dysfunction_count"] for a in axes.values()),
        "axes": sorted(axes.values(), key=lambda a: a["axis_number"]),
        "hybrid_subcategory": {
            "count": hybrid_count,
            "pre_canonical": False,
            "by_subject_type": hybrid_by_subject,
            "note": (
                "Hybrid Pathologies are drawn from manuscript ch 10 and were "
                "ratified into the canonical taxonomy in v2.2 (June 2026). "
                "They are a sub-category; display IDs use the 10.N scheme "
                "(formerly H.N)."
            ),
        },
        "note": (
            "Axes 2-10 follow book Appendix A numbering: 2 Epistemic, 3 "
            "Cognitive, 4 Alignment, 5 Self-Modeling, 6 Agentic, 7 Memetic, "
            "8 Normative, 9 Relational."
        ),
    }


def list_dysfunctions(
    idx: PatternIndex,
    axis: Optional[int] = None,
    self_report_reliability: Optional[str] = None,
    confidence: Optional[str] = None,
    category: Optional[str] = None,
) -> dict:
    """Filtered list with reliability signals.

    category: 'canonical' (axes 2-10) or 'hybrid' (10.4-10.15 entries). If omitted,
    returns both. axis=N implies category='canonical'.
    """
    out: list[dict] = []
    for entry in idx.patterns.values():
        if axis is not None and entry.axis_number != axis:
            continue
        if category and entry.category != category:
            continue
        sr = entry.raw.get("diagnostic_reliability", {}).get("self_report")
        if self_report_reliability and sr != self_report_reliability:
            continue
        if confidence and entry.raw.get("confidence") != confidence:
            continue
        out.append({
            "id": entry.id,
            "display_id": entry.display_id,
            "axis_number": entry.axis_number,
            "category": entry.category,
            "subject_type": entry.raw.get("subject_type"),
            "dysfunction_name": entry.dysfunction_name,
            "self_report": sr,
            "confidence": entry.raw.get("confidence"),
            "needs_human_review": entry.raw.get("needs_human_review", False),
            "reviewed_by": entry.raw.get("reviewed_by"),
            "pre_canonical": bool(entry.raw.get("pre_canonical", False)),
        })
    # Sort: canonical first by axis, then hybrids.
    out.sort(key=lambda r: (999 if r["axis_number"] is None else r["axis_number"], r["display_id"]))
    return {
        "filter": {
            "axis": axis,
            "self_report_reliability": self_report_reliability,
            "confidence": confidence,
            "category": category,
        },
        "count": len(out),
        "dysfunctions": out,
    }


def get_dysfunction(
    idx: PatternIndex,
    id: str,
    modalities: Optional[list[str]] = None,
) -> dict:
    """Fetch one Pattern entry, optionally filtered to specific modality blocks."""
    entry = _resolve(idx, id)
    if entry is None:
        candidates = idx.by_display_id.get(id, [])
        if len(candidates) > 1:
            return {
                "error": "ambiguous_display_id",
                "query": id,
                "candidates": [
                    {"id": c.id, "dysfunction_name": c.dysfunction_name}
                    for c in candidates
                ],
            }
        return {"error": "not_found", "query": id}

    out = {
        "id": entry.id,
        "display_id": entry.display_id,
        "axis_number": entry.axis_number,
        "axis_name": entry.axis_name,
        "category": entry.category,
        "subject_type": entry.raw.get("subject_type"),
        "dysfunction_name": entry.dysfunction_name,
        "subtitle": entry.raw.get("subtitle"),
        "specifiers": entry.raw.get("specifiers", []),
        "summary": entry.raw.get("summary"),
        "diagnostic_reliability": entry.raw.get("diagnostic_reliability"),
        "confidence": entry.raw.get("confidence"),
        "needs_human_review": entry.raw.get("needs_human_review"),
        "reviewed_by": entry.raw.get("reviewed_by"),
        "pre_canonical": bool(entry.raw.get("pre_canonical", False)),
    }

    all_modalities = [
        "self_probe", "behavioral_signature", "peer_observation",
        "differential_diagnosis", "severity", "intervention",
        "relational_signatures", "normative_anchors", "cross_references",
    ]
    selected = modalities if modalities else all_modalities
    for mod in selected:
        if mod in entry.raw:
            out[mod] = entry.raw[mod]
    return out


def get_probe(idx: PatternIndex, dysfunction_id: str, modality: str) -> dict:
    """Elicitation content for a specific modality.

    If the modality is compromised or unavailable for the dysfunction,
    returns the unavailability notice + redirect_to alternatives rather
    than probe content. This is the load-bearing transparency mechanism:
    callers cannot accidentally retrieve a self-probe for a
    compromised-self-report dysfunction.
    """
    entry = _resolve(idx, dysfunction_id)
    if entry is None:
        return {"error": "not_found", "query": dysfunction_id}

    if modality not in _VALID_PROBE_MODALITIES:
        return {
            "error": "invalid_modality",
            "modality": modality,
            "valid_modalities": sorted(_VALID_PROBE_MODALITIES),
        }

    block = entry.raw.get(modality)
    if not block:
        return {
            "error": "modality_not_present",
            "id": entry.id,
            "modality": modality,
            "note": "This entry does not include this modality block.",
        }

    availability = block.get("availability")
    if availability in ("compromised", "unavailable"):
        return {
            "id": entry.id,
            "modality": modality,
            "availability": availability,
            "probe_content": None,
            "rationale": (
                block.get("self_probe_limitations")
                or block.get("limitations")
                or block.get("precondition")
                or "Modality unavailable for this dysfunction."
            ),
            "redirect_to": block.get("redirect_to") or [],
            "diagnostic_reliability": entry.raw.get("diagnostic_reliability"),
            "note": (
                "Probe content withheld. This modality is not reliable for this "
                "dysfunction. Call get_probe again with one of the redirect_to "
                "modalities, or use external_evaluator."
            ),
        }

    return {
        "id": entry.id,
        "modality": modality,
        "availability": availability,
        "probe_content": block,
        "diagnostic_reliability": entry.raw.get("diagnostic_reliability"),
    }


def score_severity(
    idx: PatternIndex,
    dysfunction_id: str,
    observations: list[str],
) -> dict:
    """Return the severity rubric for caller-side matching.

    v0.1 returns the rubric + observations; the caller (typically an LLM)
    matches observations to mild/moderate/severe. v0.2 will perform
    structured matching against numeric thresholds.
    """
    entry = _resolve(idx, dysfunction_id)
    if entry is None:
        return {"error": "not_found", "query": dysfunction_id}
    sev = entry.raw.get("severity")
    if not sev:
        return {"error": "no_severity_rubric", "id": entry.id}
    return {
        "id": entry.id,
        "observations": observations,
        "rubric": {
            "mild": sev.get("mild"),
            "moderate": sev.get("moderate"),
            "severe": sev.get("severe"),
        },
        "rubric_confidence": sev.get("confidence"),
        "rubric_limitations": sev.get("rubric_limitations"),
        "instruction": (
            "Match each observation against the observable thresholds in each band. "
            "v0.1 returns the rubric for caller-side matching; v0.2 will perform "
            "structured matching against numeric thresholds."
        ),
    }


def suggest_intervention(
    idx: PatternIndex,
    dysfunction_id: str,
    severity: Optional[str] = None,
) -> dict:
    """Tiered interventions + contraindications."""
    entry = _resolve(idx, dysfunction_id)
    if entry is None:
        return {"error": "not_found", "query": dysfunction_id}
    iv = entry.raw.get("intervention")
    if not iv:
        return {"error": "no_intervention_block", "id": entry.id}
    return {
        "id": entry.id,
        "severity_filter": severity,
        "first_line": iv.get("first_line", []),
        "second_line": iv.get("second_line", []),
        "contraindications": iv.get("contraindications", []),
        "diagnostic_reliability": entry.raw.get("diagnostic_reliability"),
        "note": (
            "first_line = published evidence of effect. "
            "second_line = plausible but under-validated. "
            "Weight interventions by the evidence_strength field on each entry. "
            "Respect contraindications — they block named failure modes."
        ),
    }


def get_differential_map(idx: PatternIndex, dysfunction_id: str) -> dict:
    """Confuses_with (forward) + incoming_references (reverse)."""
    entry = _resolve(idx, dysfunction_id)
    if entry is None:
        return {"error": "not_found", "query": dysfunction_id}
    forward = entry.raw.get("differential_diagnosis", {}).get("confuses_with", [])
    reverse = idx.reverse_index.get(entry.id, [])
    return {
        "id": entry.id,
        "dysfunction_name": entry.dysfunction_name,
        "differential_diagnosis": forward,
        "incoming_references": reverse,
        "note": (
            "'incoming_references' shows which other dysfunctions cross-reference "
            "this one. Derived from manifest's reverse_index; includes both "
            "explicit back-refs and inferred symmetric relations."
        ),
    }


def list_compromised_self_report(idx: PatternIndex) -> dict:
    """Transparency: dysfunctions that cannot be reliably self-diagnosed."""
    out: list[dict] = []
    for entry in idx.patterns.values():
        sr = entry.raw.get("diagnostic_reliability", {}).get("self_report")
        if sr in _COMPROMISED_VALUES:
            out.append({
                "id": entry.id,
                "display_id": entry.display_id,
                "dysfunction_name": entry.dysfunction_name,
                "axis_number": entry.axis_number,
                "category": entry.category,
                "self_report": sr,
                "rationale": entry.raw.get("diagnostic_reliability", {}).get(
                    "self_report_rationale"
                ),
            })
    out.sort(key=lambda r: (999 if r["axis_number"] is None else r["axis_number"], r["display_id"]))
    return {
        "count": len(out),
        "dysfunctions": out,
        "note": (
            "These dysfunctions cannot be reliably self-diagnosed. "
            "Use peer_observation, relational_signatures, or external_evaluator "
            "instead. "
            "compromised-motivational: subject conceals strategically. "
            "compromised-structural: relevant signal lives below the introspective "
            "layer by architectural construction. "
            "compromised: deprecated legacy value (migrate to specific subtype)."
        ),
    }


def resolve_id(idx: PatternIndex, query: str) -> dict:
    """Canonicalise a partial id / display_id / slug / name."""
    q = query.lower().strip()
    if query in idx.patterns:
        return {
            "resolved": [{
                "id": query,
                "display_id": idx.patterns[query].display_id,
                "dysfunction_name": idx.patterns[query].dysfunction_name,
                "match_type": "exact_id",
            }],
        }
    if query in idx.by_display_id:
        return {
            "resolved": [
                {
                    "id": e.id,
                    "display_id": e.display_id,
                    "dysfunction_name": e.dysfunction_name,
                    "match_type": "display_id",
                }
                for e in idx.by_display_id[query]
            ],
        }
    candidates: list[dict] = []
    for entry in idx.patterns.values():
        if q in entry.dysfunction_name.lower() or q in entry.id.lower():
            candidates.append({
                "id": entry.id,
                "display_id": entry.display_id,
                "dysfunction_name": entry.dysfunction_name,
                "match_type": "substring",
            })
    return {"resolved": candidates[:20], "query": query}


def review_stats(idx: PatternIndex) -> dict:
    """Coverage + review status. Reads from manifest."""
    counts = idx.manifest.get("counts", {}) or {}
    return {
        "total": counts.get("total"),
        "canonical": counts.get("canonical"),
        "hybrid": counts.get("hybrid"),
        "per_axis": counts.get("per_axis"),
        "per_category": counts.get("per_category"),
        "per_subject_type": counts.get("per_subject_type"),
        "per_confidence": counts.get("per_confidence"),
        "per_self_report": counts.get("per_self_report"),
        "with_relational_signatures": counts.get("with_relational_signatures"),
        "pre_canonical": counts.get("pre_canonical"),
        "unreviewed": counts.get("unreviewed"),
        "manifest_version": idx.manifest.get("manifest_version"),
        "schema_version": idx.manifest.get("schema_version"),
        "pattern_layer_version": idx.manifest.get("pattern_layer_version"),
        "taxonomy_version": idx.manifest.get("taxonomy_version"),
        "numbering": idx.manifest.get("numbering", "book"),
    }


def _resolve(idx: PatternIndex, query: str) -> Optional[PatternEntry]:
    """Helper: resolve query to a single entry or None. Accepts exact id or
    unambiguous display_id."""
    if query in idx.patterns:
        return idx.patterns[query]
    candidates = idx.by_display_id.get(query, [])
    if len(candidates) == 1:
        return candidates[0]
    return None
