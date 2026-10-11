from app.models.candidate import CandidateProfile


def profile_languages(profile: CandidateProfile) -> list[str]:
    values = list(dict.fromkeys(profile.skills.get('languages', [])))
    if 'English B2' in values and 'English - daily professional use' in values:
        values = [value for value in values if value not in {'English B2', 'English - daily professional use'}]
        values.insert(0, 'English B2 — daily professional use')
    return values
