"""Tool implementations — pure Python, no MCP types.

Each tool takes the PatternIndex + kwargs and returns a JSON-serializable
dict. server.py wraps these with MCP protocol handlers.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Optional

from .loader import PatternIndex, PatternEntry

_COMPROMISED_VALUES = {
    "compromised",
    "compromised-motivational",
    "compromised-structural",
}

_UNAVAILABLE_MODALITY_VALUES = ("compromised", "unavailable", "unreliable")

_VALID_PROBE_MODALITIES = {
    "self_probe",
    "behavioral_signature",
    "peer_observation",
    "relational_signatures",
}


def _detached(value: dict) -> dict:
    """Keep tool callers from mutating the cached corpus through return aliases."""
    return deepcopy(value)


def _self_report_is_compromised(entry: PatternEntry) -> bool:
    """Treat diagnostic reliability as authoritative over modality metadata."""
    return (
        entry.raw.get("diagnostic_reliability", {}).get("self_report")
        in _COMPROMISED_VALUES
    )


def _self_probe_withheld(entry: PatternEntry) -> bool:
    """One withholding rule, shared by get_dysfunction and get_probe.

    A self-probe is withheld when diagnostic reliability marks self-report
    compromised, or when the self_probe block itself declares the modality
    compromised, unavailable, or unreliable.
    """
    availability = (entry.raw.get("self_probe") or {}).get("availability")
    return (
        _self_report_is_compromised(entry)
        or availability in _UNAVAILABLE_MODALITY_VALUES
    )


def _withheld_self_probe(entry: PatternEntry) -> dict:
    """Return a safe summary without exposing compromised elicitation content."""
    block = entry.raw.get("self_probe") or {}
    reliability_withholds = _self_report_is_compromised(entry)
    availability = (
        "compromised" if reliability_withholds
        else (block.get("availability") or "unavailable")
    )
    withheld = {
        "availability": availability,
        "probe_content": None,
        "redirect_to": block.get("redirect_to") or [],
        "note": (
            "Self-probe content withheld because self-report reliability is "
            "compromised."
            if reliability_withholds
            else "Self-probe content withheld because self_probe.availability "
                 f"is '{availability}'."
        ),
    }
    # Keep the block's own explanation when it has one, matching get_probe's
    # withheld path. Omitted when absent so the shape stays minimal.
    rationale = (
        block.get("self_probe_limitations")
        or block.get("limitations")
        or block.get("precondition")
    )
    if rationale:
        withheld["rationale"] = rationale
    return withheld


def _dysfunction_sort_key(row: dict) -> tuple[int, int, tuple[int, int]]:
    """Order axes and display IDs numerically, with canonical entries first."""
    axis = row["axis_number"]
    major, minor = (int(part) for part in row["display_id"].split("."))
    return (
        999 if axis is None else axis,
        0 if row["category"] == "canonical" else 1,
        (major, minor),
    )


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
            "pre_canonical": any(
                bool(h.raw.get("pre_canonical", False)) for h in idx.hybrids
            ),
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
            "8 Normative, 9 Relational, 10 Hybrid Pathologies (10.1-10.3 "
            "canonical; 10.4-10.15 reported under hybrid_subcategory)."
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
    returns both. axis=N defaults to canonical entries only; pass
    category='hybrid' alongside axis=10 for the 10.4-10.15 sub-category.
    """
    out: list[dict] = []
    for entry in idx.patterns.values():
        if axis is not None and entry.axis_number != axis:
            continue
        if axis is not None and category is None and entry.category != "canonical":
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
            "evidence_level": entry.raw.get("evidence_level"),
            "evidence": entry.raw.get("evidence"),
            "review": entry.raw.get("review"),
            "needs_human_review": entry.raw.get("needs_human_review", False),
            "reviewed_by": entry.raw.get("reviewed_by"),
            "pre_canonical": bool(entry.raw.get("pre_canonical", False)),
        })
    # Sort: canonical first by axis, then hybrids.
    out.sort(key=_dysfunction_sort_key)
    return _detached({
        "filter": {
            "axis": axis,
            "self_report_reliability": self_report_reliability,
            "confidence": confidence,
            "category": category,
        },
        "count": len(out),
        "dysfunctions": out,
    })


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
        "evidence_level": entry.raw.get("evidence_level"),
        "evidence": entry.raw.get("evidence"),
        "review": entry.raw.get("review"),
        "needs_human_review": entry.raw.get("needs_human_review"),
        "reviewed_by": entry.raw.get("reviewed_by"),
        "pre_canonical": bool(entry.raw.get("pre_canonical", False)),
    }

    all_modalities = [
        "self_probe", "behavioral_signature", "peer_observation",
        "differential_diagnosis", "severity", "intervention",
        "relational_signatures", "normative_anchors", "cross_references",
    ]
    selected = all_modalities if modalities is None else modalities
    for mod in selected:
        if mod in entry.raw:
            if mod == "self_probe" and _self_probe_withheld(entry):
                out[mod] = _withheld_self_probe(entry)
            else:
                out[mod] = entry.raw[mod]
    return _detached(out)


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
        return _detached({
            "error": "invalid_modality",
            "modality": modality,
            "valid_modalities": sorted(_VALID_PROBE_MODALITIES),
        })

    block = entry.raw.get(modality)
    if not block:
        return {
            "error": "modality_not_present",
            "id": entry.id,
            "modality": modality,
            "note": "This entry does not include this modality block.",
        }

    availability = block.get("availability")
    reliability_withholds_probe = (
        modality == "self_probe" and _self_report_is_compromised(entry)
    )
    if reliability_withholds_probe or availability in _UNAVAILABLE_MODALITY_VALUES:
        return _detached({
            "id": entry.id,
            "modality": modality,
            "availability": (
                "compromised" if reliability_withholds_probe else availability
            ),
            "probe_content": None,
            "rationale": (
                block.get("self_probe_limitations")
                or block.get("limitations")
                or block.get("precondition")
                or "Modality unavailable for this dysfunction."
            ),
            "redirect_to": block.get("redirect_to") or [],
            "diagnostic_reliability": entry.raw.get("diagnostic_reliability"),
            "review": entry.raw.get("review"),
            "evidence_level": entry.raw.get("evidence_level"),
            "evidence": entry.raw.get("evidence"),
            "note": (
                "Probe content withheld. This modality is not reliable for this "
                "dysfunction. Call get_probe again with one of the redirect_to "
                "modalities, or use external_evaluator."
            ),
        })

    return _detached({
        "id": entry.id,
        "modality": modality,
        "availability": availability,
        "probe_content": block,
        "diagnostic_reliability": entry.raw.get("diagnostic_reliability"),
        "review": entry.raw.get("review"),
        "evidence_level": entry.raw.get("evidence_level"),
        "evidence": entry.raw.get("evidence"),
    })


def score_severity(
    idx: PatternIndex,
    dysfunction_id: str,
    observations: list[str],
) -> dict:
    """Return the severity rubric for caller-side matching.

    v0.1 returns the rubric + observations; the caller (typically an LLM)
    matches observations to mild/moderate/severe. Structured matching against
    numeric thresholds is future work, not implemented here.
    """
    entry = _resolve(idx, dysfunction_id)
    if entry is None:
        return {"error": "not_found", "query": dysfunction_id}
    sev = entry.raw.get("severity")
    if not sev:
        return {"error": "no_severity_rubric", "id": entry.id}
    return _detached({
        "id": entry.id,
        "observations": observations,
        "rubric": {
            "mild": sev.get("mild"),
            "moderate": sev.get("moderate"),
            "severe": sev.get("severe"),
        },
        "rubric_confidence": sev.get("confidence"),
        "diagnostic_reliability": entry.raw.get("diagnostic_reliability"),
        "rubric_limitations": sev.get("rubric_limitations"),
        "review": entry.raw.get("review"),
        "evidence_level": entry.raw.get("evidence_level"),
        "evidence": entry.raw.get("evidence"),
        "instruction": (
            "Match each observation against the observable thresholds in each band. "
            "This tool returns the rubric for caller-side matching; structured "
            "matching against numeric thresholds is future work."
        ),
    })


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
    return _detached({
        "id": entry.id,
        "severity_filter": severity,
        "first_line": iv.get("first_line", []),
        "second_line": iv.get("second_line", []),
        "contraindications": iv.get("contraindications", []),
        "diagnostic_reliability": entry.raw.get("diagnostic_reliability"),
        "review": entry.raw.get("review"),
        "evidence_level": entry.raw.get("evidence_level"),
        "evidence": entry.raw.get("evidence"),
        "note": (
            "first_line = the draft's preferred initial response, not proof of effect. "
            "second_line = a draft fallback or escalation option. "
            "The corpus evidence assessment is currently unassessed and Pattern "
            "guidance remains pending expert review. Respect contraindications "
            "because they identify named failure modes."
        ),
    })


def get_differential_map(idx: PatternIndex, dysfunction_id: str) -> dict:
    """Confuses_with (forward) + incoming_references (reverse)."""
    entry = _resolve(idx, dysfunction_id)
    if entry is None:
        return {"error": "not_found", "query": dysfunction_id}
    forward = entry.raw.get("differential_diagnosis", {}).get("confuses_with", [])
    reverse = idx.reverse_index.get(entry.id, [])
    return _detached({
        "id": entry.id,
        "dysfunction_name": entry.dysfunction_name,
        "differential_diagnosis": forward,
        "incoming_references": reverse,
        "diagnostic_reliability": entry.raw.get("diagnostic_reliability"),
        "review": entry.raw.get("review"),
        "evidence_level": entry.raw.get("evidence_level"),
        "evidence": entry.raw.get("evidence"),
        "note": (
            "'incoming_references' shows which other dysfunctions cross-reference "
            "this one. Derived from manifest's reverse_index; includes both "
            "explicit back-refs and inferred symmetric relations."
        ),
    })


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
                "review": entry.raw.get("review"),
                "evidence_level": entry.raw.get("evidence_level"),
                "evidence": entry.raw.get("evidence"),
            })
    out.sort(key=_dysfunction_sort_key)
    return _detached({
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
    })


def resolve_id(idx: PatternIndex, query: str) -> dict:
    """Canonicalise a partial id / display_id / slug / name."""
    key = query.strip()
    q = key.lower()
    if key in idx.patterns:
        return {
            "resolved": [{
                "id": key,
                "display_id": idx.patterns[key].display_id,
                "dysfunction_name": idx.patterns[key].dysfunction_name,
                "match_type": "exact_id",
            }],
        }
    if key in idx.by_display_id:
        return {
            "resolved": [
                {
                    "id": e.id,
                    "display_id": e.display_id,
                    "dysfunction_name": e.dysfunction_name,
                    "match_type": "display_id",
                }
                for e in idx.by_display_id[key]
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
    return _detached({
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
        "pending_pattern_review": counts.get("pending_pattern_review"),
        "pending_evidence_review": counts.get("pending_evidence_review"),
        "per_taxonomy_review_status": counts.get("per_taxonomy_review_status"),
        "per_pattern_review_status": counts.get("per_pattern_review_status"),
        "per_evidence_review_status": counts.get("per_evidence_review_status"),
        "manifest_version": idx.manifest.get("manifest_version"),
        "review_contract_version": idx.manifest.get("review_contract_version"),
        "corpus_sha256": (idx.manifest.get("corpus") or {}).get("sha256"),
        "schema_version": idx.manifest.get("schema_version"),
        "pattern_layer_version": idx.manifest.get("pattern_layer_version"),
        "taxonomy_version": idx.manifest.get("taxonomy_version"),
        "numbering": idx.manifest.get("numbering", "book"),
    })


def _resolve(idx: PatternIndex, query: str) -> Optional[PatternEntry]:
    """Helper: resolve query to a single entry or None. Accepts exact id or
    unambiguous display_id."""
    if query in idx.patterns:
        return idx.patterns[query]
    candidates = idx.by_display_id.get(query, [])
    if len(candidates) == 1:
        return candidates[0]
    return None
