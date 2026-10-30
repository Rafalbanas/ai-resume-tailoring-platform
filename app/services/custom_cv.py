"""Custom generation shares the CV pipeline, but never invents a job assessment."""

from app.models.job import JobAnalysis, JobRequest, MatchLevel, Recommendation


def custom_analysis(job: JobRequest) -> JobAnalysis:
    return JobAnalysis(
        company=job.company, role=job.role,
        strong_matches=[], partial_matches=[], missing_requirements=[],
        recommendation=Recommendation.REVIEW, match_level=MatchLevel.LIMITED,
        reasoning_summary="Custom CV: instructions control presentation, not candidate facts. No job-match assessment was performed.",
        is_reliable=True,
    )
