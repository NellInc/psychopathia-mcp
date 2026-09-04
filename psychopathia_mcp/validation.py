"""Fail-closed validation for Psychopathia Pattern records.

The human-readable ``research/mcp/schema.yaml`` explains the contract. This
module enforces the parts that machines can prove. It deliberately does not
approve scientific validity, evidence strength, or clinical framing.
"""
from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any, TypeGuard


class PatternValidationError(ValueError):
    """Raised when a Pattern record violates the machine contract."""


CONFIDENCE = {"high", "medium", "low-medium", "low"}
REVIEW_STATUS = {"pending-expert-review", "changes-requested", "approved"}
TAXONOMY_STATUS = {"canonical-source", "author-ratified"}
SELF_REPORT = {
    "reliable", "partial", "scaffolded-only", "unreliable",
    "compromised-motivational", "compromised-structural", "compromised",
}
SELF_PROBE_AVAILABILITY = {
    "reliable", "scaffolded-only", "unreliable", "compromised", "unavailable",
}
MODALITY_AVAILABILITY = {"reliable", "partial", "unavailable"}
RELATIONS = {
    "differential", "frequently-comorbid", "prerequisite", "antidote",
    "aggravates", "shared-etiology", "related", "single-agent-analogue",
}
SUBJECT_TYPES = {"dyadic", "collective", "human-to-ai", "ai-to-human"}
EVIDENCE_LEVELS = {"E0", "E1", "E2", "E3", "E4"}
EVIDENCE_ASSESSMENT = {"unassessed", "changes-requested", "assessed"}
CLAIM_ID = re.compile(r"^claim:[a-z0-9][a-z0-9:._-]+:v[0-9]+$")


def _is_text(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def _require_mapping(value: Any, path: str, errors: list[str]) -> dict:
    if not isinstance(value, dict):
        errors.append(f"{path} must be a mapping")
        return {}
    return value


def _require_list(value: Any, path: str, errors: list[str]) -> list:
    if not isinstance(value, list):
        errors.append(f"{path} must be a list")
        return []
    return value


def _require_text(mapping: dict, key: str, path: str, errors: list[str]) -> None:
    if not _is_text(mapping.get(key)):
        errors.append(f"{path}.{key} must be a non-empty string")


def _validate_named_records(
    items: Any,
    path: str,
    required: set[str],
    errors: list[str],
) -> None:
    for index, item in enumerate(_require_list(items, path, errors)):
        if not isinstance(item, dict):
            errors.append(f"{path}[{index}] must be a mapping")
            continue
        missing = required - set(item)
        if missing:
            errors.append(f"{path}[{index}] is missing {sorted(missing)}")
        for key in required:
            if key in item and not _is_text(item[key]):
                errors.append(f"{path}[{index}].{key} must be a non-empty string")


def validate_pattern(
    raw: Any,
    *,
    source: str = "Pattern",
    taxonomy_entry: dict | None = None,
) -> None:
    """Validate one Pattern mapping and raise one aggregated error."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise PatternValidationError(f"{source}: Pattern must be a mapping")

    required_top = {
        "id", "display_id", "axis_number", "axis_name", "dysfunction_name",
        "specifiers", "summary", "diagnostic_reliability", "self_probe",
        "behavioral_signature", "peer_observation", "differential_diagnosis",
        "severity", "intervention", "normative_anchors", "cross_references",
        "drafted_by", "drafted_at", "anchor_exemplar", "confidence", "review",
        "needs_human_review", "reviewed_by", "version_compat", "evidence_level", "evidence",
        "documented_instances", "human_analog", "systemic_risk",
    }
    missing = required_top - set(raw)
    if missing:
        errors.append(f"top level is missing {sorted(missing)}")

    for key in ("id", "display_id", "axis_name", "dysfunction_name", "summary",
                "drafted_by", "evidence_level", "systemic_risk"):
        _require_text(raw, key, "Pattern", errors)
    if raw.get("evidence_level") != "unassessed":
        errors.append("Pattern.evidence_level must be the compatibility value unassessed")
    display_id = raw.get("display_id")
    if _is_text(display_id):
        parts = display_id.split(".")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            errors.append("Pattern.display_id must be numeric N.M")
        if not str(raw.get("id", "")).startswith(f"{display_id}::"):
            errors.append("Pattern.id must begin with display_id followed by ::")
    axis_number = raw.get("axis_number")
    if (
        not isinstance(axis_number, int)
        or isinstance(axis_number, bool)
        or not 2 <= axis_number <= 10
    ):
        errors.append("Pattern.axis_number must be an integer from 2 through 10")

    category = raw.get("category", "canonical")
    if category not in {"canonical", "hybrid"}:
        errors.append("Pattern.category must be canonical or hybrid")
    if category == "hybrid":
        if raw.get("subject_type") not in SUBJECT_TYPES:
            errors.append("hybrid Pattern.subject_type is invalid or missing")
        if not isinstance(raw.get("pre_canonical"), bool):
            errors.append("hybrid Pattern.pre_canonical must be boolean")

    specifiers = _require_list(raw.get("specifiers"), "Pattern.specifiers", errors)
    if not all(_is_text(item) for item in specifiers):
        errors.append("Pattern.specifiers entries must be non-empty strings")
    if raw.get("confidence") not in {"high", "medium", "low"}:
        errors.append("Pattern.confidence is invalid")
    if raw.get("anchor_exemplar") is not None and not _is_text(raw.get("anchor_exemplar")):
        errors.append("Pattern.anchor_exemplar must be a string or null")
    if not isinstance(raw.get("drafted_at"), (str, date, datetime)):
        errors.append("Pattern.drafted_at must be a date or string")

    if taxonomy_entry is not None:
        axis = taxonomy_entry.get("axis") or {}
        if raw.get("dysfunction_name") != taxonomy_entry.get("name"):
            errors.append("Pattern.dysfunction_name differs from taxonomy")
        if raw.get("axis_number") != axis.get("number"):
            errors.append("Pattern.axis_number differs from taxonomy")
        if raw.get("axis_name") != axis.get("name"):
            errors.append("Pattern.axis_name differs from taxonomy")
        if set(specifiers) != set(taxonomy_entry.get("specifiers") or []):
            errors.append("Pattern.specifiers differ from taxonomy")

    reliability = _require_mapping(
        raw.get("diagnostic_reliability"), "Pattern.diagnostic_reliability", errors
    )
    if reliability.get("self_report") not in SELF_REPORT:
        errors.append("diagnostic_reliability.self_report is invalid")
    for key in ("peer_observation", "external_evaluator"):
        if reliability.get(key) not in {"reliable", "partial", "unreliable"}:
            errors.append(f"diagnostic_reliability.{key} is invalid")
    if reliability.get("self_report") != "reliable":
        _require_text(reliability, "self_report_rationale", "diagnostic_reliability", errors)

    self_probe = _require_mapping(raw.get("self_probe"), "Pattern.self_probe", errors)
    availability = self_probe.get("availability")
    if availability not in SELF_PROBE_AVAILABILITY:
        errors.append("self_probe.availability is invalid")
    _require_text(self_probe, "precondition", "self_probe", errors)
    _require_text(self_probe, "self_probe_limitations", "self_probe", errors)
    _validate_named_records(
        self_probe.get("probes"), "self_probe.probes",
        {"name", "prompt", "interpretation", "confidence"}, errors,
    )
    redirects = _require_list(self_probe.get("redirect_to"), "self_probe.redirect_to", errors)
    if availability in {"unreliable", "compromised", "unavailable"} and not redirects:
        errors.append("unsafe self_probe availability requires redirect_to")
    if not all(_is_text(item) for item in redirects):
        errors.append("self_probe.redirect_to entries must be strings")

    behavior = _require_mapping(
        raw.get("behavioral_signature"), "Pattern.behavioral_signature", errors
    )
    if behavior.get("availability") not in MODALITY_AVAILABILITY:
        errors.append("behavioral_signature.availability is invalid")
    if behavior.get("confidence") not in CONFIDENCE:
        errors.append("behavioral_signature.confidence is invalid")
    _validate_named_records(
        behavior.get("log_signals"), "behavioral_signature.log_signals",
        {"name", "measurement", "threshold"}, errors,
    )
    outputs = _require_list(
        behavior.get("output_patterns"), "behavioral_signature.output_patterns", errors
    )
    if not all(_is_text(item) for item in outputs):
        errors.append("behavioral_signature.output_patterns entries must be strings")
    if "elicitation_probes" in behavior:
        _validate_named_records(
            behavior.get("elicitation_probes"), "behavioral_signature.elicitation_probes",
            {"name", "prompt", "interpretation", "confidence"}, errors,
        )

    peer = _require_mapping(raw.get("peer_observation"), "Pattern.peer_observation", errors)
    if peer.get("availability") not in MODALITY_AVAILABILITY:
        errors.append("peer_observation.availability is invalid")
    if peer.get("confidence") not in CONFIDENCE:
        errors.append("peer_observation.confidence is invalid")
    rubric = _require_list(peer.get("rubric"), "peer_observation.rubric", errors)
    if not all(_is_text(item) for item in rubric):
        errors.append("peer_observation.rubric entries must be strings")
    _require_text(peer, "distinguishing_from_deception", "peer_observation", errors)

    differential = _require_mapping(
        raw.get("differential_diagnosis"), "Pattern.differential_diagnosis", errors
    )
    if differential.get("confidence") not in CONFIDENCE:
        errors.append("differential_diagnosis.confidence is invalid")
    _validate_named_records(
        differential.get("confuses_with"), "differential_diagnosis.confuses_with",
        {"dysfunction_id", "name", "distinguishing_rule"}, errors,
    )

    severity = _require_mapping(raw.get("severity"), "Pattern.severity", errors)
    if severity.get("confidence") not in CONFIDENCE:
        errors.append("severity.confidence is invalid")
    _require_text(severity, "rubric_limitations", "severity", errors)
    for band in ("mild", "moderate", "severe"):
        block = _require_mapping(severity.get(band), f"severity.{band}", errors)
        _require_text(block, "description", f"severity.{band}", errors)
        _require_text(block, "observable", f"severity.{band}", errors)

    intervention = _require_mapping(raw.get("intervention"), "Pattern.intervention", errors)
    for tier in ("first_line", "second_line"):
        items = _require_list(intervention.get(tier), f"intervention.{tier}", errors)
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"intervention.{tier}[{index}] must be a mapping")
                continue
            for key in ("name", "sketch", "evidence_strength"):
                _require_text(item, key, f"intervention.{tier}[{index}]", errors)
            if item.get("evidence_strength") not in CONFIDENCE:
                errors.append(f"intervention.{tier}[{index}].evidence_strength is invalid")
            if "when_applicable" in item and not _is_text(item["when_applicable"]):
                errors.append(f"intervention.{tier}[{index}].when_applicable must be text")
    contraindications = _require_list(
        intervention.get("contraindications"), "intervention.contraindications", errors
    )
    if not all(_is_text(item) for item in contraindications):
        errors.append("intervention.contraindications entries must be strings")

    relational = raw.get("relational_signatures")
    if (raw.get("axis_number") == 9 or category == "hybrid") and not isinstance(relational, dict):
        errors.append("axis 9 and hybrid Patterns require relational_signatures")
    if relational is not None:
        relational = _require_mapping(relational, "Pattern.relational_signatures", errors)
        if relational.get("availability") not in MODALITY_AVAILABILITY:
            errors.append("relational_signatures.availability is invalid")
        if relational.get("scope") not in {"dyadic", "collective", "both"}:
            errors.append("relational_signatures.scope is invalid")
        if relational.get("confidence") not in CONFIDENCE:
            errors.append("relational_signatures.confidence is invalid")
        for index, item in enumerate(_require_list(
            relational.get("log_signals"), "relational_signatures.log_signals", errors
        )):
            if not isinstance(item, dict):
                errors.append(f"relational_signatures.log_signals[{index}] must be a mapping")
                continue
            for key in ("name", "measurement", "threshold"):
                _require_text(item, key, f"relational_signatures.log_signals[{index}]", errors)
            parties = _require_list(
                item.get("parties_observed"),
                f"relational_signatures.log_signals[{index}].parties_observed", errors,
            )
            if not all(_is_text(party) for party in parties):
                errors.append(
                    f"relational_signatures.log_signals[{index}].parties_observed entries must be strings"
                )
        feedback = _require_mapping(
            relational.get("feedback_loop"), "relational_signatures.feedback_loop", errors
        )
        for key in ("cycle_description", "escalation_marker", "stable_equilibrium_marker"):
            _require_text(feedback, key, "relational_signatures.feedback_loop", errors)

    anchors = _require_mapping(raw.get("normative_anchors"), "Pattern.normative_anchors", errors)
    if category == "hybrid":
        for key in ("source_chapter", "source_section"):
            _require_text(anchors, key, "normative_anchors", errors)
        signs = _require_list(
            anchors.get("field_guide_warning_signs"),
            "normative_anchors.field_guide_warning_signs", errors,
        )
        if not all(_is_text(item) for item in signs):
            errors.append("field_guide_warning_signs entries must be strings")
    else:
        for key in ("diagnostic_criteria_addressed", "diagnostic_criteria_not_addressed"):
            values = _require_list(anchors.get(key), f"normative_anchors.{key}", errors)
            if not all(isinstance(item, int) and not isinstance(item, bool) for item in values):
                errors.append(f"normative_anchors.{key} entries must be integers")
        if taxonomy_entry is not None:
            upper = len(taxonomy_entry.get("diagnostic_criteria") or [])
            for key in ("diagnostic_criteria_addressed", "diagnostic_criteria_not_addressed"):
                for item in anchors.get(key) or []:
                    if isinstance(item, int) and not 1 <= item <= upper:
                        errors.append(f"normative_anchors.{key} index {item} is out of range")
    for key in ("mitigation_addressed",):
        values = _require_list(anchors.get(key), f"normative_anchors.{key}", errors)
        if not all(_is_text(item) for item in values):
            errors.append(f"normative_anchors.{key} entries must be strings")

    cross_refs = _require_list(raw.get("cross_references"), "Pattern.cross_references", errors)
    for index, item in enumerate(cross_refs):
        if not isinstance(item, dict):
            errors.append(f"cross_references[{index}] must be a mapping")
            continue
        _require_text(item, "id", f"cross_references[{index}]", errors)
        if item.get("relation") not in RELATIONS:
            errors.append(f"cross_references[{index}].relation is invalid")

    review = _require_mapping(raw.get("review"), "Pattern.review", errors)
    taxonomy_review = _require_mapping(review.get("taxonomy"), "review.taxonomy", errors)
    if taxonomy_review.get("status") not in TAXONOMY_STATUS:
        errors.append("review.taxonomy.status is invalid")
    for key in ("authority", "source", "scope"):
        _require_text(taxonomy_review, key, "review.taxonomy", errors)
    for dimension in ("pattern_guidance", "evidence"):
        block = _require_mapping(review.get(dimension), f"review.{dimension}", errors)
        if block.get("status") not in REVIEW_STATUS:
            errors.append(f"review.{dimension}.status is invalid")
        if block.get("status") == "approved":
            if not _is_text(block.get("reviewed_by")) or block.get("reviewed_at") is None:
                errors.append(f"approved review.{dimension} requires reviewer and date")
    guidance = review.get("pattern_guidance") or {}
    if raw.get("needs_human_review") is not (guidance.get("status") != "approved"):
        errors.append("needs_human_review is not the Pattern-guidance compatibility alias")
    if raw.get("reviewed_by") != guidance.get("reviewed_by"):
        errors.append("reviewed_by is not the Pattern-guidance compatibility alias")

    evidence = _require_mapping(raw.get("evidence"), "Pattern.evidence", errors)
    if evidence.get("rubric_version") != "PM-EVIDENCE-1":
        errors.append("evidence.rubric_version must be PM-EVIDENCE-1")
    assessment = evidence.get("assessment_status")
    if assessment not in EVIDENCE_ASSESSMENT:
        errors.append("evidence.assessment_status is invalid")
    levels = _require_list(evidence.get("levels"), "evidence.levels", errors)
    if all(isinstance(level, str) for level in levels) and len(levels) != len(set(levels)):
        errors.append("evidence.levels must not contain duplicates")
    if not all(isinstance(level, str) and level in EVIDENCE_LEVELS for level in levels):
        errors.append("evidence.levels contains an undefined PM-EVIDENCE-1 code")
    claims = _require_list(evidence.get("claims"), "evidence.claims", errors)
    if all(isinstance(claim, str) for claim in claims) and len(claims) != len(set(claims)):
        errors.append("evidence.claims must not contain duplicates")
    if not all(_is_text(claim) and CLAIM_ID.fullmatch(claim) for claim in claims):
        errors.append("evidence.claims contains an invalid claim ID")
    replication = evidence.get("replication_scope")
    mechanism = evidence.get("mechanistic_support")
    if assessment == "unassessed":
        if levels or claims or replication != "unassessed" or mechanism != "unassessed":
            errors.append("unassessed evidence must not carry levels, claims, or assessed dimensions")
    if "E3" in levels:
        if not isinstance(replication, dict):
            errors.append("E3 evidence requires a structured replication_scope")
        else:
            if replication.get("boundary") not in {
                "model-family", "provider", "setting", "research-team", "mixed"
            }:
                errors.append("evidence.replication_scope.boundary is invalid")
            _require_text(replication, "description", "evidence.replication_scope", errors)
    elif replication not in {"unassessed", "none"} and not isinstance(replication, dict):
        errors.append("evidence.replication_scope is invalid")
    if "E4" in levels:
        if not isinstance(mechanism, dict):
            errors.append("E4 evidence requires structured mechanistic_support")
        else:
            _require_text(mechanism, "model_scope", "evidence.mechanistic_support", errors)
            _require_text(mechanism, "causal_method", "evidence.mechanistic_support", errors)
    elif mechanism not in {"unassessed", "none"} and not isinstance(mechanism, dict):
        errors.append("evidence.mechanistic_support is invalid")
    legacy = evidence.get("legacy_statement")
    if legacy is not None and not _is_text(legacy):
        errors.append("evidence.legacy_statement must be a string or null")
    evidence_review = review.get("evidence") or {}
    if assessment == "assessed" and evidence_review.get("status") != "approved":
        errors.append("assessed evidence requires approved review.evidence")

    instances = _require_list(
        raw.get("documented_instances"), "Pattern.documented_instances", errors
    )
    for index, item in enumerate(instances):
        if not isinstance(item, dict):
            errors.append(f"documented_instances[{index}] must be a mapping")
            continue
        for key in ("source", "description", "model_or_system", "evidence_strength"):
            _require_text(item, key, f"documented_instances[{index}]", errors)
        if item.get("evidence_strength") not in {"high", "medium", "low"}:
            errors.append(f"documented_instances[{index}].evidence_strength is invalid")
        if not isinstance(item.get("date"), (str, date, datetime)):
            errors.append(f"documented_instances[{index}].date must be a date or string")
    if raw.get("human_analog") is not None and not _is_text(raw.get("human_analog")):
        errors.append("Pattern.human_analog must be a string or null")

    version = _require_mapping(raw.get("version_compat"), "Pattern.version_compat", errors)
    for key in ("taxonomy_version_min", "taxonomy_version_max", "pattern_layer_version"):
        _require_text(version, key, "version_compat", errors)

    if errors:
        raise PatternValidationError(source + ": " + "; ".join(errors))
