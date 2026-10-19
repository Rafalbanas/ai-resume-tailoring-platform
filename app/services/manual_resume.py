"""Explicit per-document manual edits; never change global generation policy."""
from copy import deepcopy

from app.services.resume_edit_validation import ManualEditResult

MANUAL_WARNING = "Truth Lock is off for this CV. Manually edited claims have not been checked against the profile."


def truth_lock_level(metadata):
    return metadata.get('truth_lock_level', 1.0 if metadata.get('truth_lock_enabled', True) else 0.0)


def check_edit(validator, original, edited, job, slug, metadata):
    level = truth_lock_level(metadata)
    if level == 0:
        return manual_edit(original, edited, slug)
    return validator.validate_manual_edit(original, edited, job, allow_manual_skills=level < 1)


def manual_edit(original, edited, slug):
    resume = deepcopy(edited)
    if resume.professional_summary != original.professional_summary:
        resume.summary_source_fact_ids = []
        resume.summary_attestation = ''
    if resume.core_skills != original.core_skills:
        resume.selected_skill_ids = []
    for i, experience in enumerate(resume.experience):
        for j, bullet in enumerate(experience.bullets):
            if not any(bullet == previous for previous in original.experience[i].bullets):
                bullet.source_fact_ids = [f'manual:{slug}:experience:{i}:{j}']
    for i, project in enumerate(resume.projects):
        if project != original.projects[i]:
            project.source_fact_ids = [f'manual:{slug}:project:{i}']
    return ManualEditResult(resume=resume, warnings=[MANUAL_WARNING])
