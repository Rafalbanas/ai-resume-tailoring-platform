from copy import deepcopy

from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, MatchLevel, Recommendation
from app.services.fact_catalog import FactCatalog


def _append_unique(values: list[str], value: str) -> None:
    if value.casefold() not in {item.casefold() for item in values}:
        values.append(value)


class AnalysisValidator:
    """Makes match classifications provable against the active master profile."""

    def __init__(self, profile: CandidateProfile):
        self.catalog = FactCatalog(profile)

    def validate(self, candidate: JobAnalysis) -> JobAnalysis:
        result = deepcopy(candidate)
        strong: list[str] = []
        partial: list[str] = []
        missing: list[str] = []
        sources: dict[str, list[str]] = {}

        for claim in result.strong_matches:
            claimed_ids = result.match_sources.get(claim, [])
            direct_ids = self.catalog.direct_sources(claim)
            valid_ids = [entry.source_id for entry in self.catalog.valid(claimed_ids)]
            supporting_ids = direct_ids or (valid_ids if self.catalog.supports(claim, valid_ids) else [])
            if supporting_ids:
                _append_unique(strong, claim)
                sources[claim] = supporting_ids
            elif valid_ids and self.catalog.related(claim, valid_ids):
                _append_unique(partial, claim)
                sources[claim] = valid_ids
            else:
                _append_unique(missing, claim)

        for claim in result.partial_matches:
            direct_ids = self.catalog.direct_sources(claim)
            claimed_ids = [entry.source_id for entry in self.catalog.valid(result.match_sources.get(claim, []))]
            if direct_ids:
                _append_unique(strong, claim)
                sources[claim] = direct_ids
            elif claimed_ids and self.catalog.related(claim, claimed_ids):
                _append_unique(partial, claim)
                sources[claim] = claimed_ids
            else:
                _append_unique(missing, claim)

        for claim in result.missing_requirements:
            direct_ids = self.catalog.direct_sources(claim)
            if direct_ids:
                _append_unique(strong, claim)
                sources[claim] = direct_ids
            else:
                _append_unique(missing, claim)

        result.strong_matches = strong
        result.partial_matches = partial
        result.missing_requirements = [
            value for value in missing if value.casefold() not in {item.casefold() for item in strong + partial}
        ]
        result.match_sources = sources

        supported_keywords = []
        unsupported_keywords = []
        for keyword in result.supported_keywords:
            if self.catalog.direct_sources(keyword):
                _append_unique(supported_keywords, keyword)
            else:
                _append_unique(unsupported_keywords, keyword)
        for keyword in result.unsupported_keywords:
            if self.catalog.direct_sources(keyword):
                _append_unique(supported_keywords, keyword)
            else:
                _append_unique(unsupported_keywords, keyword)
        result.supported_keywords = supported_keywords
        result.unsupported_keywords = unsupported_keywords

        total = len(strong) + len(partial) + len(result.missing_requirements)
        score = (len(strong) + 0.5 * len(partial)) / max(1, total)
        if score >= 0.7:
            result.match_level = MatchLevel.HIGH
            result.recommendation = Recommendation.APPLY
        elif score >= 0.4:
            result.match_level = MatchLevel.MEDIUM
            result.recommendation = Recommendation.REASONABLE_STRETCH
        else:
            result.match_level = MatchLevel.LOW
            result.recommendation = Recommendation.SKIP

        strong_text = ", ".join(strong[:5]) or "no direct requirements"
        partial_text = ", ".join(partial[:4]) or "no transferable requirements"
        missing_text = ", ".join(result.missing_requirements[:5]) or "no material gaps"
        result.reasoning_summary = (
            f"Verified master-profile facts directly support {strong_text}. "
            f"Transferable evidence supports {partial_text}. "
            f"Unverified or missing requirements are {missing_text}."
        )[:600]
        return result
