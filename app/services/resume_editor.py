from collections.abc import Mapping
from copy import deepcopy

from app.models.resume import TailoredResume


def _split_values(value: object, original=()) -> list[str]:
    values = []
    for line in str(value or "").splitlines():
        saved = next((item for item in original if item.strip() == line.strip()), None)
        if saved is not None:
            values.append(saved)
        else:
            values.extend(item.strip() for item in line.split(",") if item.strip())
    return values


def _edited_text(value, original):
    text = str(value)
    return original if text == original else text.strip()


def apply_resume_edits(resume: TailoredResume, form: Mapping[str, object]) -> TailoredResume:
    draft = deepcopy(resume)
    draft.headline = _edited_text(form.get("headline", draft.headline), draft.headline)
    draft.professional_summary = _edited_text(form.get("professional_summary", draft.professional_summary), draft.professional_summary)
    if "core_skills" in form:
        draft.core_skills = _split_values(form.get("core_skills"), resume.core_skills)
        if draft.core_skills != resume.core_skills:
            draft.selected_skill_ids = []  # The scoped validator resolves visible values, not positional IDs.


    if "currently_learning" in form:
        # This control only removes saved declarations; additions require bank validation.
        retained = str(form.get("currently_learning") or "").splitlines()
        draft.currently_learning = [item for item in resume.currently_learning
                                    if f"{item.name} — {item.status}" in retained]

    for exp_index, experience in enumerate(draft.experience):
        clean_bullets = []
        for bullet_index, bullet in enumerate(experience.bullets):
            key = f"experience_{exp_index}_bullet_{bullet_index}"
            text = _edited_text(form.get(key, bullet.text), bullet.text)
            if text:
                bullet.text = text
                clean_bullets.append(bullet)
        experience.bullets = clean_bullets

    for project_index, project in enumerate(draft.projects):
        project.description = _edited_text(form.get(f"project_{project_index}_description", project.description), project.description)
        technologies = form.get(f"project_{project_index}_technologies")
        if technologies is not None:
            project.technologies = list(project.technologies) if str(technologies) == ", ".join(project.technologies) else _split_values(technologies, project.technologies)

    if "interests" in form:
        draft.interests = list(resume.interests) if str(form.get("interests")) == ", ".join(resume.interests) else _split_values(form.get("interests"), resume.interests)
    elif form.get("interests_enabled") == "off" or (
        "interests_enabled" in form and form.get("interests_enabled") != "on"
    ):
        draft.interests = []

    if draft.interests != resume.interests:
        draft.selected_interest_ids = []
    validated = TailoredResume.model_validate(draft.model_dump())
    validated.summary_attestation = draft.summary_attestation
    return validated

