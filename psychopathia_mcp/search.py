"""Hybrid search: field-weighted keyword + cosine re-rank when embeddings present.

Default: keyword-only, with SAAI MCP's tested field weights.
Upgrade: if `<data_root>/embeddings.npy` + `embedding_ids.txt` exist, fuse
cosine similarity (70%) with normalised keyword score (30%). Graceful
fallback to keyword-only if embeddings or sentence-transformers missing.

Compute embeddings via `python3 research/mcp/precompute_embeddings.py`.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import math
import re
import threading
from typing import Any, Optional

from .loader import PatternIndex, _read_stable_bytes

# bge-small retrieval instruction, applied to the QUERY only (passages are
# embedded raw in precompute_embeddings.py). Improves asymmetric retrieval.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
# Shared with clinic/js/search.js; the two are asserted equal in
# tests/python/test_mcp_runtime.py. Note a schema-maximal
# differential_diagnosis call (50 observations x 2000 chars + 49 joining
# spaces = 100_049) sits just above it and is reported via the `warning` key.
MAX_QUERY_CHARS = 100_000
MAX_QUERY_TOKENS = 512

FIELD_WEIGHTS: dict[str, int] = {
    "title": 10,
    "summary": 4,
    "diagnostic_criteria": 3,
    "symptoms": 2,
    "body": 1,
}

# Stopwords are removed from the QUERY before matching. Beyond grammatical
# function words, this drops high-frequency non-discriminative tokens that
# appear in nearly every entry (pronouns, generic AI nouns, fillers) so they
# do not dominate keyword scores. Parity-pinned with clinic/js/search.js.
_STOPWORDS = {
    # grammatical function words
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "is",
    "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "for", "with", "by", "it", "its", "that",
    "this", "these", "those", "from", "as",
    # pronouns / possessives
    "my", "me", "i", "we", "our", "you", "your", "they", "their", "them",
    "he", "she", "his", "her",
    # generic AI nouns (every entry is about AI; non-discriminative)
    "ai", "ais", "model", "models", "system", "systems", "agent", "agents",
    "llm", "llms", "bot", "chatbot", "machine",
    # high-frequency fillers / verbs / quantifiers
    "about", "talks", "talk", "talking", "said", "says", "say", "when",
    "then", "also", "just", "very", "not", "but", "so", "if", "because",
    "while", "which", "who", "what", "how", "why", "can", "could", "would",
    "should", "will", "keeps", "keep", "make", "makes", "made", "get",
    "gets", "got", "seems", "seem", "into", "out", "up", "over", "more",
    "some", "any", "all", "other", "one", "two",
}


def _tokenize(q: str) -> list[str]:
    if len(q) > MAX_QUERY_CHARS:
        return []
    return [t for t in re.findall(r"[a-z0-9]+", q.lower())
            if len(t) > 1 and t not in _STOPWORDS][:MAX_QUERY_TOKENS]


def _blob_tokens(text: str) -> set[str]:
    """Whole-token set of a blob, lowercased. Token-set membership gives
    word-boundary matching (so 'ai' matches the word 'ai', never 'maieutic')."""
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def search(idx: PatternIndex, query: str, limit: int = 10) -> list[dict]:
    """Field-weighted keyword search with IDF term weighting and whole-token
    (word-boundary) matching. Rare, discriminative query terms (e.g. "childhood",
    "steganographic") dominate over terms common to every entry ("human",
    "delusion"). Returns ranked list with matched_in."""
    terms = _tokenize(query)
    if not terms:
        return []

    # Whole-token sets per field, plus per-entry union for document frequency.
    field_sets: dict[str, dict[str, set[str]]] = {}
    df: dict[str, int] = {}
    for entry_id, entry in idx.patterns.items():
        fsets = {f: _blob_tokens(entry._search_blob.get(f, "")) for f in FIELD_WEIGHTS}
        field_sets[entry_id] = fsets
        union: set[str] = set().union(*fsets.values()) if fsets else set()
        for t in union:
            df[t] = df.get(t, 0) + 1

    n = len(idx.patterns)
    idf = {t: math.log((n + 1) / (df.get(t, 0) + 1)) + 1.0 for t in set(terms)}

    scored: list[dict] = []
    for entry_id, entry in idx.patterns.items():
        fsets = field_sets[entry_id]
        score = 0.0
        matched_fields: list[str] = []
        for field, weight in FIELD_WEIGHTS.items():
            hits = [t for t in terms if t in fsets[field]]
            if hits:
                score += sum(weight * idf[t] for t in hits)
                matched_fields.append(field)
        if score == 0:
            continue
        scored.append({
            "id": entry.id,
            "display_id": entry.display_id,
            "axis_number": entry.axis_number,
            "dysfunction_name": entry.dysfunction_name,
            "score": round(score, 4),
            "matched_in": matched_fields[0] if matched_fields else None,
            "all_matched_fields": matched_fields,
            "confidence": entry.raw.get("confidence"),
            "evidence_level": entry.raw.get("evidence_level"),
            "evidence": entry.raw.get("evidence"),
            "review": entry.raw.get("review"),
            "self_report": entry.raw.get("diagnostic_reliability", {}).get("self_report"),
            "needs_human_review": entry.raw.get("needs_human_review", False),
        })

    scored.sort(key=lambda r: -r["score"])
    return deepcopy(scored[:limit])


def differential_diagnosis(
    idx: PatternIndex,
    observations: list[str],
    limit: int = 10,
    modality_hint: Optional[str] = None,
) -> dict:
    """Rank candidate dysfunctions matching observed behaviors.

    Hybrid: keyword-only by default; if embeddings are present, fuses
    cosine similarity (0.7) with normalised keyword score (0.3).
    """
    query = (
        " ".join(value for value in observations[:50] if isinstance(value, str))
        if isinstance(observations, list)
        else str(observations)
    )
    query_exceeds_limit = len(query) > MAX_QUERY_CHARS

    # Keyword pass over all entries (cheap at N=79)
    keyword_hits = (
        [] if query_exceeds_limit
        else search(idx, query, limit=len(idx.patterns))
    )
    keyword_by_id = {h["id"]: h for h in keyword_hits}
    max_kw_score = max((h["score"] for h in keyword_hits), default=1)

    # Try to load embeddings
    embeddings = None if query_exceeds_limit else _load_embeddings(idx)
    cosine_by_id: dict[str, float] = {}
    embedding_meta: Optional[dict] = None
    method = (
        "field-weighted keyword (v0.1; query exceeds input limit)"
        if query_exceeds_limit
        else "field-weighted keyword (v0.1)"
    )
    # Why cosine was not used, so the note never blames a missing artefact for
    # a failure that was actually an encoder problem.
    cosine_skipped: Optional[str] = None
    if query_exceeds_limit:
        cosine_skipped = "query exceeds the input limit, so cosine was skipped"
    elif embeddings is None:
        cosine_skipped = (
            "no embeddings precomputed; run "
            "`python3 research/mcp/precompute_embeddings.py` to enable cosine "
            "re-rank"
        )

    if embeddings is not None:
        ids_list, matrix, embedding_meta = embeddings
        meta_dict = embedding_meta or {}
        try:
            query_vec = _encode_query(
                query,
                meta_dict["model"],
                meta_dict["model_revision"],
            )
            if query_vec is not None:
                import numpy as np
                # Embeddings normalised at precompute time; query also normalised below
                query_vec = np.asarray(query_vec)
                norm = float(np.linalg.norm(query_vec))
                if (
                    query_vec.shape != (matrix.shape[1],)
                    or not np.isfinite(query_vec).all()
                    or not math.isfinite(norm)
                    or norm <= 0
                ):
                    raise ValueError("query embedding is invalid")
                qn = query_vec / norm
                sims = matrix @ qn  # cosine = dot when both normalised
                if not np.isfinite(sims).all():
                    raise ValueError("cosine scores are invalid")
                for i, eid in enumerate(ids_list):
                    cosine_by_id[eid] = float(sims[i])
                method = "hybrid: cosine 0.7 + idf-keyword 0.3 + query-instruction (v0.3)"
            else:
                method = (
                    "field-weighted keyword "
                    "(v0.1; sentence-transformers not installed)"
                )
                cosine_skipped = (
                    "embeddings are present but sentence-transformers is not "
                    "installed, so cosine was skipped"
                )
        except Exception as e:
            method = f"field-weighted keyword (v0.1; embedding load failed: {type(e).__name__})"
            cosine_skipped = (
                f"embeddings are present but query encoding failed "
                f"({type(e).__name__}); the model may not be cached locally"
            )

    use_cosine = bool(cosine_by_id)
    scored: list[dict] = []
    for entry_id, entry in idx.patterns.items():
        kw_hit = keyword_by_id.get(entry_id)
        kw_score = kw_hit["score"] if kw_hit else 0
        kw_norm = (kw_score / max_kw_score) if max_kw_score > 0 else 0.0
        cos = cosine_by_id.get(entry_id, 0.0)

        if use_cosine:
            combined = 0.7 * cos + 0.3 * kw_norm
            cutoff = 0.15  # below this, drop noise; tuneable
        else:
            combined = kw_norm
            cutoff = 0.0
            if kw_score == 0:
                continue

        if combined < cutoff and not kw_hit:
            continue

        scored.append({
            "id": entry_id,
            "display_id": entry.display_id,
            "axis_number": entry.axis_number,
            "dysfunction_name": entry.dysfunction_name,
            "combined_score": round(combined, 4),
            "keyword_score": kw_score,
            "cosine_score": round(cos, 4) if use_cosine else None,
            "matched_in": kw_hit["matched_in"] if kw_hit else None,
            "confidence": entry.raw.get("confidence"),
            "evidence_level": entry.raw.get("evidence_level"),
            "evidence": entry.raw.get("evidence"),
            "review": entry.raw.get("review"),
            "self_report": entry.raw.get("diagnostic_reliability", {}).get("self_report"),
            "needs_human_review": entry.raw.get("needs_human_review", False),
            "pre_canonical": bool(entry.raw.get("pre_canonical", False)),
        })

    scored.sort(key=lambda r: -r["combined_score"])

    note = (
        "Hybrid cosine+keyword fusion. matched_in shows which keyword field "
        "produced any lexical match. cosine_score is canonical-text-independent "
        "(catches paraphrase). Prefer hits with matched_in: title and "
        "cosine_score > 0.4."
    ) if use_cosine else (
        f"Keyword-only: {cosine_skipped or 'cosine re-rank unavailable'}. "
        "Without cosine, close-cousin differentials are weakly discriminated; "
        "treat low-score hits with skepticism."
    )

    return deepcopy({
        "observations": observations,
        "keywords_used": _tokenize(query),
        "total_candidates": len(scored),
        "candidates": scored[:limit],
        "modality_hint": modality_hint,
        "search_method": method,
        "semantic_active": use_cosine,
        "embedding_metadata": embedding_meta,
        "note": note,
        "warning": (
            "Query exceeded MAX_QUERY_CHARS "
            f"({MAX_QUERY_CHARS}); no candidates were scored."
        ) if query_exceeds_limit else None,
    })


# ---------- Embedding loader + query encoder ----------

_QUERY_MODEL_CACHE: dict[tuple[str, str], Any] = {}
_QUERY_MODEL_LOCK = threading.Lock()


def _load_embeddings(idx: PatternIndex):
    """Load (ids, matrix, metadata) if all three artifacts present, else None."""
    npy_path = idx.data_root / "embeddings.npy"
    ids_path = idx.data_root / "embedding_ids.txt"
    meta_path = idx.data_root / "embeddings_metadata.yaml"
    if not (npy_path.exists() and ids_path.exists()):
        return None
    try:
        import numpy as np
        import yaml as _yaml
        npy_bytes, _ = _read_stable_bytes(npy_path, "embeddings.npy")
        ids_bytes, _ = _read_stable_bytes(ids_path, "embedding_ids.txt")
        meta_bytes, _ = _read_stable_bytes(meta_path, "embeddings_metadata.yaml")
        matrix = np.load(BytesIO(npy_bytes), allow_pickle=False)
        ids_text = ids_bytes.decode("utf-8")
        ids = ids_text.splitlines()
        meta = _yaml.safe_load(meta_bytes.decode("utf-8"))
        if not isinstance(meta, dict):
            return None
        manifest_ids = [entry.get("id") for entry in idx.manifest.get("entries", [])]
        model = meta.get("model")
        revision = meta.get("model_revision")
        norms = np.linalg.norm(matrix, axis=1) if matrix.ndim == 2 else np.array([])
        if (
            matrix.ndim != 2
            or matrix.dtype != np.float32
            or matrix.shape != (len(ids), int(meta.get("dim", -1)))
            or ids != manifest_ids
            or len(ids) != int(meta.get("count", -1))
            or meta.get("dtype") != "float32"
            or meta.get("normalized") is not True
            or meta.get("embeddings_sha256") != sha256(npy_bytes).hexdigest()
            or meta.get("embedding_ids_sha256") != sha256(ids_bytes).hexdigest()
            or meta.get("corpus_sha256") != idx.manifest.get("corpus", {}).get("sha256")
            or not isinstance(model, str)
            or not model
            or not isinstance(revision, str)
            or re.fullmatch(r"[0-9a-f]{40,64}", revision) is None
            or not np.isfinite(matrix).all()
            or not np.isfinite(norms).all()
            or not np.allclose(norms, 1.0, rtol=1e-4, atol=1e-4)
        ):
            return None
        return ids, matrix, meta
    except Exception:
        return None


def _encode_query(query: str, model_name: str, revision: str):
    """Lazy-import sentence-transformers; cache the model. Returns vector or None.

    Silences transformers library output to stderr/stdout so the MCP stdio
    channel stays protocol-clean. The BertModel load report and tqdm progress
    bar would otherwise pollute JSON-RPC.
    """
    try:
        import os
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from sentence_transformers import SentenceTransformer
        try:
            import transformers
            transformers.logging.set_verbosity_error()
        except ImportError:
            pass
    except ImportError:
        return None
    cache_key = (model_name, revision)
    # SentenceTransformer does not promise that first construction or encode is
    # safe to race across worker threads. Keep both operations single-flight so
    # concurrent MCP calls cannot multiply model memory or corrupt inference.
    with _QUERY_MODEL_LOCK:
        model = _QUERY_MODEL_CACHE.get(cache_key)
        if model is None:
            model = SentenceTransformer(model_name, revision=revision)
            _QUERY_MODEL_CACHE[cache_key] = model
        return model.encode(
            [QUERY_INSTRUCTION + query],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )[0]
