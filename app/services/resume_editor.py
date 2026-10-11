from collections.abc import Mapping
from copy import deepcopy

from app.models.resume import TailoredResume


def _split_values(value: object) -> list[str]:
    return [item.strip() for line in str(value or "").splitlines() for item in line.split(",") if item.strip()]


def apply_resume_edits(resume: TailoredResume, form: Mapping[str, object]) -> TailoredResume:
    draft = deepcopy(resume)
    draft.headline = str(form.get("headline", draft.headline)).strip()
    draft.professional_summary = str(form.get("professional_summary", draft.professional_summary)).strip()
    if "core_skills" in form:
        draft.core_skills = _split_values(form.get("core_skills"))
        # A manual list replaces the model selection; Truth Lock resolves it back to bank IDs.
        original_ids = dict(zip(resume.core_skills, resume.selected_skill_ids, strict=False))
        draft.selected_skill_ids = [original_ids[value] for value in draft.core_skills if value in original_ids]

    for exp_index, experience in enumerate(draft.experience):
        clean_bullets = []
        for bullet_index, bullet in enumerate(experience.bullets):
            key = f"experience_{exp_index}_bullet_{bullet_index}"
            text = str(form.get(key, bullet.text)).strip()
            if text:
                bullet.text = text
                clean_bullets.append(bullet)
        experience.bullets = clean_bullets

    for project_index, project in enumerate(draft.projects):
        project.description = str(form.get(f"project_{project_index}_description", project.description)).strip()
        technologies = form.get(f"project_{project_index}_technologies")
        if technologies is not None:
            project.technologies = _split_values(technologies)

    if "interests" in form:
        draft.interests = _split_values(form.get("interests"))
    elif form.get("interests_enabled") == "off" or (
        "interests_enabled" in form and form.get("interests_enabled") != "on"
    ):
        draft.interests = []

    return TailoredResume.model_validate(draft.model_dump())

