import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import ValidationError

from app.core.config import Settings
from app.models.candidate import CandidateProfile


class ProfileConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProfileStatus:
    source: str
    profile_kind: str
    valid: bool

    def public(self) -> dict[str, str | bool]:
        return asdict(self)


def _is_example(profile: CandidateProfile, path: Path) -> bool:
    marker = " ".join([profile.personal.name, *profile.summary_facts]).casefold()
    return (
        "example" in path.name.casefold()
        or "alex example" in marker
        or "replace this sentence" in marker
        or "fictional portfolio example" in marker
    )


def load_master_profile(settings: Settings) -> tuple[CandidateProfile, ProfileStatus]:
    path = settings.master_profile_path
    source = str(path)
    if not path.is_file():
        raise ProfileConfigurationError(
            f"Production master profile is missing at {source}. "
            "Create data/master_profile.json from verified candidate facts; the example profile is never a fallback."
        )
    try:
        profile = CandidateProfile.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, json.JSONDecodeError):
        raise ProfileConfigurationError(f"Master profile at {source} is invalid; check the schema and JSON syntax.") from None

    is_example = _is_example(profile, path)
    kind = "example" if is_example else "production"
    if settings.profile_mode == "production":
        problems = []
        if is_example:
            problems.append("the active file is an example or template")
        if not profile.personal.name.strip():
            problems.append("candidate name is missing")
        if not any(
            value.strip() for value in (profile.personal.email, profile.personal.phone, profile.personal.linkedin)
        ):
            problems.append("candidate contact details are missing")
        if not profile.summary_facts:
            problems.append("summary facts are missing")
        if not profile.experience:
            problems.append("professional experience is missing")
        if not profile.education:
            problems.append("education is missing")
        if not any(profile.skills.values()):
            problems.append("skills are missing")
        if problems:
            raise ProfileConfigurationError(
                f"Production master profile at {source} is not usable: {', '.join(problems)}. "
                "The application will not fall back to data/master_profile.example.json."
            )
    return profile, ProfileStatus(source=source, profile_kind=kind, valid=True)


def save_master_profile(profile: CandidateProfile, settings: Settings) -> None:
    import os
    import tempfile

    path = settings.master_profile_path
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".profile-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(profile.model_dump_json(indent=2))
            handle.write("\n")
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

