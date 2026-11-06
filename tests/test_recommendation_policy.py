import pytest

from app.models.job import MatchLevel, Recommendation
from app.services.recommendation_policy import qualification_recommendation


@pytest.mark.parametrize("confirmed, partial, missing, confirmed_absence, expected_level, expected_recommendation", [
    (8, 0, 0, False, MatchLevel.HIGH, Recommendation.APPLY),
    (8, 1, 0, False, MatchLevel.MEDIUM, Recommendation.REASONABLE_STRETCH),
    (0, 1, 0, False, MatchLevel.MEDIUM, Recommendation.REVIEW),
    (0, 0, 3, False, MatchLevel.LOW, Recommendation.REVIEW),
    (1, 0, 1, False, MatchLevel.MEDIUM, Recommendation.REVIEW),
    (1, 0, 2, False, MatchLevel.LOW, Recommendation.REVIEW),
    (2, 0, 1, False, MatchLevel.MEDIUM, Recommendation.REASONABLE_STRETCH),
    (0, 0, 0, False, MatchLevel.LIMITED, Recommendation.REVIEW),
    (8, 0, 1, True, MatchLevel.MEDIUM, Recommendation.SKIP),
])
def test_qualification_recommendation(confirmed, partial, missing, confirmed_absence, expected_level, expected_recommendation):
    level, recommendation = qualification_recommendation(
        confirmed=confirmed,
        partial=partial,
        missing=missing,
        confirmed_absence=confirmed_absence
    )
    assert level == expected_level
    assert recommendation == expected_recommendation
