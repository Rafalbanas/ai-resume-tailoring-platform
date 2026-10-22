"""Request-local lexical retrieval. Scores select context, never establish competence."""
import hashlib
import json
import logging
import math
from collections import Counter
from dataclasses import dataclass

from app.models.job import JobAnalysis, JobRequest
from app.services.fact_catalog import FactEntry, normalized_tokens

logger = logging.getLogger(__name__)
TOP_K = 24
MAX_CONTEXT_CHARS = 16000


@dataclass
class RetrievalResult:
    entries: list[FactEntry]
    trace: dict


def _documents(catalog, bank):
    # The master profile is the canonical attested source. SkillsBank may impose
    # additional restrictions; learning/disabled skills must not bypass them here.
    return [e for e in catalog.prompt_entries if e.kind != "interest" and (
        e.kind != "skill" or bank is None or (
            (skill := bank.find(e.text)) is not None and bank.eligible(skill)
        )
    )]


def _anchors(documents):
    """Keep chronology, education identities and one summary even without hits."""
    seen = set()
    result = []
    for entry in documents:
        key = (entry.kind, entry.owner_index)
        if (entry.kind in {"summary", "experience"} or (
            entry.kind == "education" and entry.source_id.count(":") == 1
        )) and key not in seen:
            seen.add(key)
            result.append(entry)
    return result


class FactIndex:
    """An ephemeral BM25 index owned by one request, with no global/persisted cache."""

    def __init__(self, documents):
        self.documents = documents
        self.tokens = [Counter(t for word in e.text.split() for t in normalized_tokens(word)) for e in documents]
        self.df = Counter(token for tokens in self.tokens for token in tokens)
        self.average_length = sum(sum(tokens.values()) for tokens in self.tokens) / max(1, len(documents))

    def search(self, queries):
        scores = {}
        n = len(self.documents)
        for query, weight in queries:
            terms = normalized_tokens(query)
            for entry, tokens in zip(self.documents, self.tokens, strict=True):
                score = 0.0
                for term in sorted(terms & tokens.keys()):
                    df = self.df[term]
                    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                    tf = tokens[term]
                    score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * sum(tokens.values()) / self.average_length))
                if score:
                    scores[entry.source_id] = scores.get(entry.source_id, 0) + weight * score / max(1, len(terms))
        return sorted(((e, scores[e.source_id]) for e in self.documents if e.source_id in scores),
                      key=lambda item: (-item[1], item[0].source_id))


def retrieve_facts(job: JobRequest, profile, analysis: JobAnalysis, bank=None,
                   *, top_k=TOP_K, max_chars=MAX_CONTEXT_CHARS) -> RetrievalResult:
    from app.services.cv_content_policy import cv_catalog
    catalog = cv_catalog(profile, job)
    documents = _documents(catalog, bank)
    selected = {e.source_id: e for e in _anchors(documents)}
    reasons = {i: "identity_anchor" for i in selected}
    scores = {}
    # Requirements originate in the posting, not in candidate documents. Quoted
    # text remains data; source IDs suggested by a model do not control retrieval.
    requirements = [*analysis.requirements, *analysis.role_competencies]
    queries = [(r.name, 2.0 if r.priority == "mandatory" else 1.0) for r in requirements]
    if not queries:
        queries = [(job.job_description, 1.0)]
    queries.append((job.role, 0.5))
    mode = "ranked"
    try:
        ranked = FactIndex(documents).search(queries)
        # Blend lexical relevance with the canonical profile order. Only ranked
        # matches participate: this control cannot create evidence for a gap.
        maximum = max((score for _, score in ranked), default=1)
        source_order = {e.source_id: index for index, e in enumerate(documents)}
        level = job.tailoring_level
        ranking_scores = {
            e.source_id: (1 - level) * score / maximum
            + level * (1 - source_order[e.source_id] / max(1, len(documents)))
            for e, score in ranked
        }
        ranked.sort(key=lambda item: (-ranking_scores[item[0].source_id], item[0].source_id))
        mode = "ranked" if ranked else "no_matches"
        used = sum(len(e.text) for e in selected.values())
        for entry, score in ranked[:top_k]:
            if entry.source_id not in selected:
                if used + len(entry.text) > max_chars:
                    continue
                selected[entry.source_id] = entry
                used += len(entry.text)
            reasons[entry.source_id] = "lexical_match"
            scores[entry.source_id] = round(score, 6)
    except Exception:
        # No exception text or candidate data in logs. The previous full catalog
        # behavior is safe only because the same Truth Lock still guards export.
        logger.warning("Fact retrieval unavailable; using canonical catalog fallback")
        mode = "catalog_fallback"
        selected = {e.source_id: e for e in documents}
        reasons = {i: "catalog_fallback" for i in selected}
    entries = list(selected.values())
    return RetrievalResult(entries, {
        "method": "local_bm25", "mode": mode, "top_k": top_k,
        "tailoring_level": job.tailoring_level,
        "ranking_policy": "blend_normalized_bm25_with_profile_order",
        "index_revision": hashlib.sha256(json.dumps(
            [(e.source_id, e.kind, e.owner_name, e.text) for e in documents],
            ensure_ascii=False).encode()).hexdigest(),
        "queries": [{"text": q, "weight": w} for q, w in queries],
        "max_context_chars": max_chars, "document_count": len(documents),
        "selected": [{"source_id": e.source_id, "type": e.kind, "owner": e.owner_name,
                      "reason": reasons[e.source_id], "score": scores.get(e.source_id, 0),
                      "ranking_score": round(ranking_scores.get(e.source_id, 0), 6) if mode == 'ranked' else 0}
                     for e in entries],
    })
