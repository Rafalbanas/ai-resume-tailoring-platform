"""Validate new claims against sources; audit saved claims without rewriting them."""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field

from app.services.fact_validator import ValidationResult


@dataclass
class ManualEditResult(ValidationResult):
    issues: list[dict[str, str]] = field(default_factory=list)


def validate_manual_edit(validator, original, edited, job):
    result = ManualEditResult(deepcopy(edited), [])
    checked = validator.validate(edited, job, preserve_skills=True).resume

    def reject(path, reason, suggestion):
        result.issues.append(dict(field=path, reason=reason, suggestion=suggestion))

    def audit(path):
        result.warnings.append(f'Existing content requires review — {path}: current sources do not retain this saved wording or its citations. Review the profile evidence or regenerate this section. It was not rewritten by this edit.')

    def skill(value):
        bank = validator.skills_bank
        if not bank:
            return None
        return next((s for s in bank.skills if bank.wording(s) == value), None) or bank.find(value)

    old_skills = Counter(original.core_skills)
    for value, count in Counter(edited.core_skills).items():
        entry = skill(value)
        supported = (bool(entry and validator.skills_bank.eligible(entry)) if validator.skills_bank
                     else value in [s for values in validator.profile.skills.values() for s in values])
        canonical = validator.skills_bank.wording(entry) if entry and supported else None
        if count > old_skills[value]:
            if not supported or (canonical is not None and canonical != value):
                reject(f'Skills: {value}', 'New or changed wording is not approved at this competence level.',
                       f'Use the verified wording: {canonical}.' if canonical else 'Remove this addition, or verify its scope and evidence in Skills Bank first.')
        elif not supported or (canonical is not None and canonical != value):
            audit(f'Skills: {value}')
    if edited.core_skills != original.core_skills:
        # Resolve by actual rendered wording, never by positional zip with stale IDs.
        result.resume.selected_skill_ids = list(dict.fromkeys(s.id for value in edited.core_skills
            if (s := skill(value)) and validator.skills_bank.eligible(s) and validator.skills_bank.wording(s) == value)) if validator.skills_bank else []
    elif validator.skills_bank and set(original.selected_skill_ids) != {s.id for value in original.core_skills if (s := skill(value)) and validator.skills_bank.eligible(s) and validator.skills_bank.wording(s) == value}:
        audit('Skills source IDs')

    for path in ('headline', 'professional_summary'):
        before, after, validated = getattr(original, path), getattr(edited, path), getattr(checked, path)
        if before != after:
            if after and after != validated:
                reject(path, 'Current source validation would replace this changed claim.',
                       f'Use source-backed wording: {validated}' if validated else 'Remove this claim or update its verified source facts first.')
        elif after and after != validated:
            audit(path)

    checked_experience = {(e.company, e.title): e for e in checked.experience}
    for index, experience in enumerate(edited.experience):
        old = original.experience[index]
        validated = checked_experience.get((experience.company, experience.title))
        supported_text = {b.text for b in validated.bullets} if validated else set()
        if validated is None or experience.dates != validated.dates:
            audit(f"experience_{index}: owner/dates/source references")
        old_claims = Counter((b.text, tuple(b.source_fact_ids)) for b in old.bullets)
        for bullet_index, bullet in enumerate(experience.bullets):
            key = (bullet.text, tuple(bullet.source_fact_ids))
            path = f'experience_{index}_bullet_{bullet_index}'
            unchanged = old_claims[key] > 0
            old_claims[key] -= 1
            entries = validator.catalog.valid(bullet.source_fact_ids, kind="experience")
            owners = {e.owner_index for e in entries}
            owner = validator.profile.experience[next(iter(owners))] if len(owners) == 1 and None not in owners else None
            supported_citations = bool(owner and (owner.company, owner.title) == (experience.company, experience.title)) and (
                validator.catalog.supports_paraphrase(bullet.text, [e.source_id for e in entries])
                or any(bullet.text == validator._experience_wording(e.text) for e in entries))
            if not unchanged and supported_citations and bullet.text in supported_text:
                result.resume.experience[index].bullets[bullet_index].source_fact_ids = list(dict.fromkeys(e.source_id for e in entries))
            if bullet.text not in supported_text or not supported_citations:
                if unchanged:
                    audit(path)
                else:
                    reject(path, 'The edited bullet is not supported by its employment citations.',
                           'Use wording from the cited employment facts, or remove this bullet. Regenerate the section if its owner/citations are outdated.')

    checked_projects = {p.name: p for p in checked.projects}
    for index, project in enumerate(edited.projects):
        old = original.projects[index]
        validated = checked_projects.get(project.name)
        path = f'project_{index}_description'
        entries = validator.catalog.valid(project.source_fact_ids, kind="project")
        owners = {entry.owner_index for entry in entries}
        valid_owner = len(owners) == 1 and None not in owners and validator.profile.projects[next(iter(owners))].name == project.name
        if not valid_owner:
            audit(f"project_{index}: source references")
        if validated and project.url != validated.url:
            audit(f"project_{index}: URL")
        valid_description = validated.description if validated else None
        if validated is None:
            audit(f"project_{index}: owner/source references")
        if project.description != old.description:
            if project.description and (not valid_owner or project.description != valid_description):
                reject(path, 'The changed project description is not supported by its project citations.',
                       f'Use source-backed wording: {valid_description}' if valid_description else 'Remove the description or repair this project’s source references first.')
            elif project.description and validated:
                result.resume.projects[index].source_fact_ids = list(validated.source_fact_ids)
        elif project.description and project.description != valid_description:
            audit(path)
        valid_technologies = set(validated.technologies) if validated else set()
        old_technologies = Counter(old.technologies)
        for technology, count in Counter(project.technologies).items():
            if technology not in valid_technologies or (count > old_technologies[technology] and not valid_owner):
                path = f'project_{index}_technologies: {technology}'
                if count > old_technologies[technology]:
                    reject(path, 'This technology or level is not verified for this project.', 'Remove the addition or verify project-specific evidence first.')
                else:
                    audit(path)

    interests = {i.name: i for i in validator.profile.interests if i.enabled and i.verified and i.allowed_in_cv}
    for name in set(edited.interests):
        if name not in interests:
            if name not in original.interests:
                reject(f'interests: {name}', 'This interest is not approved for CV export.', 'Remove the addition or confirm it in your profile first.')
            else:
                audit(f'interests: {name}')
    if edited.interests != original.interests:
        result.resume.selected_interest_ids = [interests[name].id for name in edited.interests if name in interests]
    for section in ('education', 'certifications'):
        if getattr(edited, section) != getattr(checked, section):
            audit(section)
    return result
