"""Conservative application advice, separate from qualification match levels."""

from app.models.job import MatchLevel, Recommendation


def qualification_recommendation(
    *, confirmed: int, partial: int, missing: int, confirmed_absence: bool = False,
) -> tuple[MatchLevel, Recommendation]:
    """Assess distinct mandatory groups; missing evidence is not inability.

    A stretch needs at least one fully supported group and fewer than half
    unsupported groups. These are advice thresholds, not hiring probabilities.
    Confirmed mandatory gaps cannot be outweighed by unrelated strengths.
    """
    total = confirmed + partial + missing
    if not total:
        return MatchLevel.LIMITED, Recommendation.REVIEW
    score = (confirmed + .5 * partial) / total
    level = (MatchLevel.HIGH if confirmed == total else
             MatchLevel.MEDIUM if score >= .4 else MatchLevel.LOW)
    if confirmed_absence:
        return level, Recommendation.SKIP
    if confirmed == total:
        return level, Recommendation.APPLY
    if score >= .4 and confirmed > 0 and missing / total < .5:
        return level, Recommendation.REASONABLE_STRETCH
    return level, Recommendation.REVIEW
