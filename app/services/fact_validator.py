import re
from copy import deepcopy
from dataclasses import dataclass

from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import (
    ResumeBullet,
    ResumeCertification,
    ResumeEducation,
    ResumeExperience,
    ResumeProject,
    TailoredResume,
)
from app.services.content_quality import evidence_specificity, generic_duty, high_value_detail, scope_mentions
from app.services.fact_catalog import FactCatalog, normalized_tokens
from app.services.languages import is_language_skill
from app.services.professional_summary import build_summary, deduplicate_summary
from app.services.role_focus import TargetFocus, target_focus
from app.services.skills_bank import GENERATED_CV_SKILL_TARGET, SkillsBank


def _headline_with_suffix(occupation: str, suffixes: list[str]) -> str:
    """Fit whole eligible labels; never truncate the actual occupation."""
    parts = suffixes[:2]
    if len(parts) == 2:
        combined = occupation + ' | ' + ' · '.join(parts)
        if len(combined) <= 64:
            return combined
    return next((occupation + ' | ' + part for part in parts
                 if len(occupation + ' | ' + part) <= 64), occupation)


def _profile_headline(value: str, occupation: str, skills: list[str]) -> str | None:
    """Accept compositions of whole attested labels, never a generated occupation.

    Match complete labels rather than splitting on punctuation: a skill or actual
    job title can itself contain '/', '&' or a level qualifier.
    """
    if len(value) > 140:
        return None
    from itertools import permutations
    for left, right in permutations(dict.fromkeys(skills), 2):
        if value == f"{left} & {right} | {occupation}":
            return value
    for left, right in permutations(dict.fromkeys([occupation, *skills]), 2):
        for separator in (' & ', ' / ', ' — ', ' · ', ' | '):
            if value == left + separator + right:
                return value
    return None


@dataclass
class ValidationResult:
    resume: TailoredResume
    warnings: list[str]


class FactValidator:
    """Turns model output into profile-backed data; prompts are never the trust boundary."""

    def __init__(self, profile: CandidateProfile, skills_bank: SkillsBank | None = None, analysis: JobAnalysis | None = None, *, review_key: str = ""):
        self.profile = profile
        self.catalog = FactCatalog(profile)
        self.skills_bank = skills_bank
        self.analysis = analysis
        self.review_key = review_key
        self.fact_priorities: dict[str, float] = {}
        self._posting_cache: tuple[str, str, set[str]] | None = None
        self._focus_cache: tuple[tuple[str, str, str], TargetFocus] | None = None
        if analysis:
            for position, requirement in enumerate([*analysis.requirements, *analysis.role_competencies]):
                if requirement.status not in {'strong', 'partial'}:
                    continue
                # Preserve the model's ordering within the same priority rather
                # than allowing a long, generic citation to dominate the summary.
                weight = (3 if requirement.priority == 'mandatory' else 1) / (1 + position * 0.05)
                for source_id in requirement.source_fact_ids:
                    entry = self.catalog.get(source_id)
                    canonical = entry.source_id if entry else source_id
                    self.fact_priorities[canonical] = max(weight, self.fact_priorities.get(canonical, 0))
            # Resolve the verified skills index back to its documented usage.
            # Ranking can use these facts; it does not upgrade a skill's level.
            if self.skills_bank:
                for source_id, weight in list(self.fact_priorities.items()):
                    entry = self.catalog.get(source_id)
                    skill = self.skills_bank.get(source_id.removeprefix('skill:'))
                    skill = skill or (self.skills_bank.find(entry.text) if entry else None)
                    if entry and entry.kind == 'skill':
                        terms = normalized_tokens(entry.text) - {'basic', 'administration', 'automation', 'scripting', 'working', 'knowledge'}
                        if terms:
                            for fact in self.catalog.prompt_entries:
                                if fact.kind in {'summary', 'experience', 'project'} and terms <= normalized_tokens(fact.text):
                                    self.fact_priorities[fact.source_id] = max(weight, self.fact_priorities.get(fact.source_id, 0))
                    if skill and self.skills_bank.eligible(skill):
                        for evidence in skill.evidence:
                            fact = self.catalog.get(evidence.source_id)
                            if fact and self.skills_bank.evidence_supports(skill, evidence):
                                self.fact_priorities[fact.source_id] = max(weight, self.fact_priorities.get(fact.source_id, 0))

        self._analysis_priorities = self.fact_priorities.copy()

    def validate_manual_edit(self, original: TailoredResume, edited: TailoredResume, job: JobRequest, *, allow_manual_skills: bool = False):
        from app.services.resume_edit_validation import validate_manual_edit
        return validate_manual_edit(self, original, edited, job, allow_manual_skills=allow_manual_skills)

    def validate(self, candidate: TailoredResume, job: JobRequest, *, preserve_skills: bool = False) -> ValidationResult:
        from app.services.cv_content_policy import cv_catalog
        self.catalog = cv_catalog(self.profile, job)
        self.fact_priorities = self._analysis_priorities.copy()
        if self.analysis is not None and not preserve_skills:
            from app.services.job_sections import relevance_text
            posting = relevance_text(f"{job.role}\n{job.relevance_text}")
            # Rank attested employment details even when analysis cited only a
            # global skill. This never transfers global claims into an employer.
            topics = [r"\bnetworks?\b|\bnetworking\b", r"\bcollaborat\w*\b", r"\bescalat\w*\b"]
            for entry in self.catalog.prompt_entries:
                if entry.kind != "experience":
                    continue
                shared = sum(bool(re.search(t, posting, re.I) and re.search(t, entry.text, re.I)) for t in topics)
                if shared:
                    self.fact_priorities[entry.source_id] = max(self.fact_priorities.get(entry.source_id, 0), 0.25 * shared)
        draft = deepcopy(candidate)
        if job.workflow != 'custom' and not preserve_skills:
            draft.section_order = self._section_order(job)
            draft.excluded_sections = []
        warnings: list[str] = []
        learning = self.skills_bank.learning_for_job(f"{job.role}\n{job.relevance_text}") if self.skills_bank else []
        if preserve_skills:
            requested = {item.skill_id for item in candidate.currently_learning}
            learning = [item for item in learning if item.skill_id in requested]
        if candidate.currently_learning and candidate.currently_learning != learning:
            warnings.append("Currently learning: unsupported entries or wording replaced by user-confirmed learning declarations.")
        draft.currently_learning = learning

        def skill_key(value: str) -> str:
            return " ".join(value.casefold().replace("(basic)", "").replace("/", " ").replace("-", " ").split())

        allowed_skills = {skill_key(value): value for values in self.profile.skills.values() for value in values if not is_language_skill(value, self.profile)}
        clean_skills = []
        if self.skills_bank:
            requested_ids = list(draft.selected_skill_ids)
            for value in draft.core_skills:
                skill = next((self.skills_bank.get(skill_id) for skill_id in draft.selected_skill_ids
                    if self.skills_bank.get(skill_id) and self.skills_bank.wording(self.skills_bank.get(skill_id)) == value), None)
                skill = skill or self.skills_bank.find(value)
                if skill and self.skills_bank.eligible(skill):
                    requested_ids.append(skill.id)
                elif value.strip():
                    warnings.append(f"Unsupported AI fact removed: {value}")
            selected = self.skills_bank.select_for_job(
                list(dict.fromkeys(requested_ids)),
                f"{job.role}\n{job.relevance_text}",
                minimum=0 if preserve_skills else GENERATED_CV_SKILL_TARGET,
                maximum=16,
                requested_only=preserve_skills,
                tailoring_level=job.tailoring_level,
            )
            if self.fact_priorities and not preserve_skills and job.tailoring_level == 0:
                focus = self._target(job)
                job_order = {s.id: rank for rank, s in enumerate(selected)}

                def evidence_priority(skill):
                    ids = [f'skill:{skill.id}', *(e.source_id for e in skill.evidence)]
                    return max((self.fact_priorities.get(
                        entry.source_id if (entry := self.catalog.get(i)) else i, 0) for i in ids), default=0)

                selected.sort(key=lambda s: (
                    -int(focus.evidence_led and bool(normalized_tokens(s.name) <= focus.terms)),
                    -focus.score(' '.join(self.skills_bank.aliases_for(s))),
                    -evidence_priority(s), job_order[s.id]))
            draft.selected_skill_ids = [skill.id for skill in selected]
            draft.core_skills = [self.skills_bank.wording(skill) for skill in selected]
            allowed_skills = {
                skill_key(alias): self.skills_bank.wording(skill)
                for skill in self.skills_bank.skills
                if self.skills_bank.eligible(skill)
                for alias in self.skills_bank.aliases_for(skill)
            }
        else:
            focus = self._target(job)
            context_terms = focus.terms if focus.evidence_led else normalized_tokens(f"{job.role}\n{job.relevance_text}")
            for skill in draft.core_skills:
                key = skill_key(skill)
                if key in allowed_skills:
                    canonical = allowed_skills[key]
                    if canonical not in clean_skills:
                        clean_skills.append(canonical)
                else:
                    warnings.append(f"Unsupported AI fact removed: {skill}")
            if not clean_skills and not preserve_skills:
                relevant = [
                    canonical
                    for key, canonical in allowed_skills.items()
                    if key and normalized_tokens(canonical) and
                    (normalized_tokens(canonical) - {'basic', 'junior', 'theoretical'}) <= context_terms
                ]
                clean_skills = relevant
            if not preserve_skills and len(clean_skills) < GENERATED_CV_SKILL_TARGET:
                remaining = sorted(dict.fromkeys(allowed_skills.values()),
                                   key=lambda value: -len(normalized_tokens(value) & context_terms))
                for value in remaining:
                    if value not in clean_skills:
                        clean_skills.append(value)
                    if len(clean_skills) >= GENERATED_CV_SKILL_TARGET:
                        break
            draft.core_skills = clean_skills[:18]
            if not preserve_skills:
                source_order = list(dict.fromkeys(allowed_skills.values()))
                target = sorted(source_order, key=lambda s: (len(normalized_tokens(s) & context_terms),
                                      focus.score(s) if focus.evidence_led else 0), reverse=True)
                weight = job.tailoring_level ** 2
                draft.core_skills.sort(key=lambda s: (
                    focus.evidence_led and job.tailoring_level <= .5 and not focus.direct_terms(s),
                    (1 - weight) * target.index(s) + weight * source_order.index(s)))

        verified_headline = self._build_headline(job.role, draft.selected_skill_ids, draft.core_skills)
        occupation = verified_headline
        # A direction is accepted only as exact eligible skill wording after
        # the real occupation. Keep the existing advertised-title fallback.
        pieces = [s.strip() for s in draft.headline.split('|')]
        pieces[0] = re.sub(r'\bTier\s*([123])\b', r'L\1', pieces[0], flags=re.I)
        suffixes = []
        if len(pieces) == 2 and pieces[0] == occupation:
            parts = [pieces[1]] if pieces[1] in draft.core_skills else pieces[1].split(' · ')
            if 1 <= len(parts) <= 2 and all(part in draft.core_skills for part in parts):
                suffixes = parts
        if (self.analysis is not None and job.tailoring_level < 0.75
                and draft.headline.strip() == job.role.strip() and draft.headline.strip() != occupation):
            suffixes = draft.core_skills[:2]
        verified_headline = _headline_with_suffix(occupation, suffixes)
        # Both generated and manually retained headlines resolve whole labels
        # against the same current profile and eligible skill selection.
        profile_headline = _profile_headline(draft.headline.strip(), occupation, draft.core_skills)
        verified_headline = profile_headline or verified_headline
        if (not preserve_skills and job.workflow != 'custom' and job.tailoring_level < 0.75
                and (draft.headline.strip() in {occupation, job.role.strip(), ''}
                     or (not profile_headline and self._target(job).evidence_led))):
            verified_headline = self._direction_headline(occupation, draft.core_skills, job)
        if draft.headline.strip() and draft.headline.strip() not in {job.role.strip(), verified_headline}:
            warnings.append("Unsupported or non-deterministic headline was replaced with verified role and skills")
        draft.headline = verified_headline

        summary_role = (f"{job.role}\n{job.relevance_text}" if job.tailoring_level < 1
                        else occupation)
        summary, summary_ids = build_summary(self.catalog, summary_role, priorities=self.fact_priorities,
                                            tailoring_level=job.tailoring_level,
                                            focus=self._target(job) if job.workflow == 'job' else None)
        summary_entries = self.catalog.valid(draft.summary_source_fact_ids)
        model_ids = [e.source_id for e in summary_entries if e.kind in {"summary", "experience", "project"}
                     and (e.kind == "summary" or ":fact:" in e.source_id)]
        sentence_count = len(re.split(r"(?<=[.!?])\s+(?=[A-Z])", draft.professional_summary.strip()))
        from app.services.content_quality import deduplicate_bullets, deduplicate_text, quality_issues, unfinished
        from app.services.cv_content_policy import internal_annotation, networking_terminology_issue
        from app.services.ml_terminology import ml_terminology_issue
        from app.services.summary_review import sign_source_summary, sign_summary, valid_summary_attestation
        reviewed = (all(self.catalog.get(i) for i in draft.summary_source_fact_ids)
                    and not internal_annotation(draft.professional_summary)
                    and not networking_terminology_issue(draft.professional_summary)
                    and valid_summary_attestation(draft, self.profile, self.review_key))
        if reviewed:
            model_ids = [e.source_id for e in summary_entries]
        project_scope_missing = any(e.kind == 'project' for e in summary_entries) and not re.search(
            r'\bproject\w*\b|\bportfolio\b|\bthesis\b|\bacademic\b|\bprojekt\w*\b',
            draft.professional_summary, re.I)
        from app.services.professional_summary import broken_activity_summary, employment_scope_issue
        if (unfinished(draft.professional_summary) or networking_terminology_issue(draft.professional_summary)
                or ml_terminology_issue(draft.professional_summary)
                or broken_activity_summary(draft.professional_summary, summary_entries)
                or len(re.findall(r'\bproject work(?:\s*:|\s+includes\b)', draft.professional_summary, re.I)) > 1
                or project_scope_missing
                or employment_scope_issue(draft.professional_summary, summary_entries, self.profile)
                or (sentence_count > 5 and not reviewed)
                or (not reviewed and not preserve_skills and sentence_count < 3 and len(draft.professional_summary) < 300
                    and len(set(summary_ids)) >= 3
                    and len(re.split(r"(?<=[.!?])\s+(?=[A-Z])", summary)) >= 3)
                or not (reviewed or self.catalog.supports_paraphrase(draft.professional_summary, model_ids))):
            if draft.professional_summary != summary:
                warnings.append("Professional summary rebuilt from scoped verified source sentences; model tone cannot be assessed from this replacement")
            draft.professional_summary = summary
            draft.summary_source_fact_ids = summary_ids
            draft.summary_attestation = ''
            reviewed = False
        else:
            draft.summary_source_fact_ids = model_ids
        draft.professional_summary = deduplicate_summary(draft.professional_summary, self.catalog)
        draft.professional_summary = deduplicate_text(draft.professional_summary)
        if reviewed:
            draft.summary_attestation = sign_summary(draft, self.profile, self.review_key)
        elif self.review_key:
            # Only the deterministic path reaches here without a model approval:
            # exact source text or the source-sentence builder above. Preserve
            # its provenance separately from a semantic model verdict.
            draft.summary_attestation = sign_source_summary(draft, self.profile, self.review_key)
        clean_experience: list[ResumeExperience] = []
        accepted_bullet_attestations = []
        for exp in draft.experience:
            bullets = []
            exp_index: int | None = None
            for bullet in exp.bullets:
                entries = self.catalog.valid(bullet.source_fact_ids, kind="experience")
                owner_indexes = {entry.owner_index for entry in entries}
                if len(owner_indexes) != 1:
                    warnings.append(f"Unsupported AI bullet removed from {exp.company}")
                    continue
                bullet_index = owner_indexes.pop()
                if bullet_index is None or (exp_index is not None and bullet_index != exp_index):
                    warnings.append(f"Unsupported AI bullet removed from {exp.company}")
                    continue
                exp_index = bullet_index
                valid_ids = [entry.source_id for entry in entries]
                from app.services.ollama_draft_review import sign_bullet, valid_bullet_attestation
                reviewed_bullet = (all(self.catalog.get(i) for i in bullet.source_fact_ids)
                                   and valid_bullet_attestation(bullet, draft, self.profile, self.review_key))
                if (not reviewed_bullet and not self.catalog.supports_paraphrase(bullet.text, valid_ids)
                        and not any(bullet.text == self._experience_wording(entry.text) for entry in entries)
                        and bullet.text != self._experience_wording(" ".join(entry.text for entry in entries))):
                    warnings.append(f"Unsupported AI bullet replaced in {self.profile.experience[exp_index].company}")
                    bullet.text = " ".join(entry.text for entry in entries)
                bullet.text = self._experience_wording(bullet.text)
                bullet.source_fact_ids = valid_ids
                if not preserve_skills and job.workflow == 'job' and job.tailoring_level < 1:
                    # A valid but empty paraphrase should not suppress the
                    # substantial, permitted source it already cites.
                    if generic_duty(bullet.text) and any(not generic_duty(e.text) for e in entries):
                        bullet.text = self._experience_wording(" ".join(entry.text for entry in entries))
                        reviewed_bullet = False
                if reviewed_bullet:
                    accepted_bullet_attestations.append(sign_bullet(bullet, self.profile, self.review_key))
                bullets.append(bullet)
            if exp_index is None or not bullets:
                warnings.append(f"Unsupported AI experience removed: {exp.company} — {exp.title}")
                continue
            source = self.profile.experience[exp_index]
            exp.company = source.company
            exp.title = source.title
            exp.dates = " – ".join(filter(None, [source.start, source.end]))
            if not preserve_skills:
                cited = {i for b in bullets for i in b.source_fact_ids}
                for entry in self._experience_entries(exp_index, job):
                    if entry.source_id in cited:
                        if not self._lacks_source_detail(entry, bullets, job):
                            continue
                        bullets = [b for b in bullets if b.source_fact_ids != [entry.source_id]]
                    bullets.append(ResumeBullet(text=self._experience_wording(entry.text), source_fact_ids=[entry.source_id]))
                bullets = self._rank_bullets(bullets, job)
            exp.bullets = deduplicate_bullets(bullets)[:4]
            clean_experience.append(exp)
        if not clean_experience:
            for exp_index, source in enumerate(self.profile.experience):
                entries = self._experience_entries(exp_index, job)
                if not entries:
                    continue
                clean_experience.append(
                    ResumeExperience(
                        company=source.company,
                        title=source.title,
                        dates=" – ".join(filter(None, [source.start, source.end])),
                        bullets=[ResumeBullet(text=self._experience_wording(entry.text), source_fact_ids=[entry.source_id]) for entry in entries],
                    )
                )
        unique_experience = {}
        for item in clean_experience:
            key = (item.company, item.title, item.dates)
            if key not in unique_experience:
                unique_experience[key] = item
            else:
                existing = unique_experience[key]
                known = {bullet.text for bullet in existing.bullets}
                merged = existing.bullets + [bullet for bullet in item.bullets if bullet.text not in known]
                existing.bullets = deduplicate_bullets(merged if preserve_skills else self._rank_bullets(merged, job))[:4]
        clean_experience = list(unique_experience.values())
        included = {(item.company, item.title, item.dates) for item in clean_experience}
        for index, source in enumerate(self.profile.experience):
            dates = " – ".join(filter(None, [source.start, source.end]))
            if (source.company, source.title, dates) in included:
                continue
            entries = self._experience_entries(index, job)
            if entries:
                clean_experience.append(ResumeExperience(
                    company=source.company, title=source.title, dates=dates,
                    bullets=[ResumeBullet(text=self._experience_wording(e.text), source_fact_ids=[e.source_id]) for e in entries],
                ))
        order = {(e.company, e.title): i for i, e in enumerate(self.profile.experience)}
        clean_experience.sort(key=lambda e: order.get((e.company, e.title), len(order)))
        draft.experience = clean_experience
        draft._bullet_attestations = accepted_bullet_attestations

        clean_projects: list[ResumeProject] = []
        for project in draft.projects:
            entries = self.catalog.valid(project.source_fact_ids, kind="project")
            owner_indexes = {entry.owner_index for entry in entries}
            if len(owner_indexes) != 1:
                warnings.append(f"Unsupported AI project removed: {project.name}")
                continue
            index = owner_indexes.pop()
            if index is None:
                warnings.append(f"Unsupported AI project content removed: {project.name}")
                continue
            source = self.profile.projects[index]
            valid_ids = [entry.source_id for entry in entries]
            project.name = source.name
            project.url = source.url if source.url.startswith(("https://", "http://")) else ""
            canonical_description, canonical_ids = self._project_content(source, job, summary=draft.professional_summary)
            attested_descriptions = {source.description, *source.facts}
            attested_descriptions.add(canonical_description)
            if project.description not in attested_descriptions:
                warnings.append(f"Project wording replaced with verified description: {project.name}")
            if not preserve_skills:
                project.description = canonical_description
            elif project.description not in attested_descriptions:
                project.description = canonical_description
            project.source_fact_ids = ((canonical_ids or valid_ids)
                                       if project.description == canonical_description else valid_ids)
            verified_technologies = [
                tech for tech in source.technologies if skill_key(tech) in allowed_skills
            ]
            requested_technologies = []
            unsupported_technologies = []
            for value in project.technologies:
                canonical = allowed_skills.get(skill_key(value))
                if canonical:
                    requested_technologies.append(canonical)
                else:
                    unsupported_technologies.append(value)
            source_technology_keys = {skill_key(allowed_skills.get(skill_key(value), value)) for value in verified_technologies}
            unsupported_technologies.extend(
                value for value in requested_technologies if skill_key(value) not in source_technology_keys
            )
            if unsupported_technologies:
                warnings.append(
                    f"Unsupported technologies removed from project {project.name}: "
                    f"{', '.join(dict.fromkeys(unsupported_technologies))}"
                )
            project.technologies = verified_technologies
            if project.name not in {item.name for item in clean_projects}:
                clean_projects.append(project)
        selected_project_names = {project.name.casefold() for project in clean_projects}
        for index, source in enumerate(self.profile.projects):
            if source.name.casefold() in selected_project_names:
                continue
            entries = [
                entry
                for entry in self.catalog.prompt_entries
                if entry.kind == "project" and entry.owner_index == index
            ]
            content = next((entry for entry in entries if ":description:" in entry.source_id), None)
            content = content or next(iter(entries), None)
            if content and (":description:" in content.source_id or ":fact:" in content.source_id):
                description, content_ids = self._project_content(source, job, summary=draft.professional_summary)
                clean_projects.append(
                    ResumeProject(
                        name=source.name,
                        url=source.url if source.url.startswith(("https://", "http://")) else "",
                        description=description,
                        technologies=[
                            tech
                            for tech in source.technologies
                            if skill_key(tech) in allowed_skills
                        ],
                        source_fact_ids=content_ids,
                    )
                )
        ranked_projects = self._rank_projects(clean_projects, job)
        if (not preserve_skills and job.workflow == 'job' and job.tailoring_level <= 0.5
                and (focus := self._target(job)).duties and focus.evidence_led):
            # A merely documented project isn't necessarily worth space in a
            # tightly tailored CV. Keep projects with contextual evidence, not
            # those sharing only a generic word such as "configuration".
            all_projects = {p.name: p for p in self.profile.projects}
            ranked_projects = [p for p in ranked_projects if any(
                self.fact_priorities.get(e.source_id, 0)
                or (focus.score(e.text) and focus.direct_terms(e.text))
                for e in self.catalog.valid(p.source_fact_ids, kind='project'))
                or (p.name in all_projects and any(
                    focus.score(tech) and focus.direct_terms(tech) for tech in all_projects[p.name].technologies))]
        if len(ranked_projects) > 2 and self._project_relevance(ranked_projects[2], job) > 0:
            draft.projects = ranked_projects[:3]
        else:
            draft.projects = ranked_projects[:2]
        thesis_in_projects = any("thesis" in p.name.casefold() for p in draft.projects)

        clean_education = []
        education_lookup = {
            item.institution.casefold(): (index, item) for index, item in enumerate(self.profile.education)
        }
        for item in draft.education:
            entries = self.catalog.valid(item.source_fact_ids, kind="education")
            index = entries[0].owner_index if entries else None
            if index is None:
                match = education_lookup.get(item.institution.casefold())
                index = match[0] if match else None
            if index is None:
                warnings.append(f"Unsupported AI education removed: {item.institution}")
                continue
            source = self.profile.education[index]
            if source.institution in {item.institution for item in clean_education}:
                continue
            main_entry = next(
                (
                    entry
                    for entry in self.catalog.prompt_entries
                    if entry.kind == "education" and entry.owner_index == index and ":fact:" not in entry.source_id
                ),
                None,
            )
            thesis_subline = ""
            specialisation = ""
            if not thesis_in_projects and getattr(source, "thesis_title", None):
                thesis_subline = f"Thesis: {source.thesis_title}"
            if getattr(source, "specialisation", None):
                specialisation = f"Specialisation: {source.specialisation}"
            clean_education.append(
                ResumeEducation(
                    institution=source.institution,
                    qualification=source.qualification,
                    dates=source.dates,
                    specialisation=specialisation,
                    thesis_subline=thesis_subline,
                    source_fact_ids=[main_entry.source_id] if main_entry else [],
                )
            )
        included_institutions = {item.institution.casefold() for item in clean_education}
        if len(included_institutions) < len(self.profile.education):
            for index, source in enumerate(self.profile.education):
                if source.institution.casefold() in included_institutions:
                    continue
                main_entry = next(
                    (
                        entry
                        for entry in self.catalog.prompt_entries
                        if entry.kind == "education" and entry.owner_index == index and ":fact:" not in entry.source_id
                    ),
                    None,
                )
                thesis_subline = ""
                specialisation = ""
                if not thesis_in_projects and getattr(source, "thesis_title", None):
                    thesis_subline = f"Thesis: {source.thesis_title}"
                if getattr(source, "specialisation", None):
                    specialisation = f"Specialisation: {source.specialisation}"
                clean_education.append(
                    ResumeEducation(
                        institution=source.institution,
                        qualification=source.qualification,
                        dates=source.dates,
                        specialisation=specialisation,
                        thesis_subline=thesis_subline,
                        source_fact_ids=[main_entry.source_id] if main_entry else [],
                    )
                )
        draft.education = clean_education

        allowed_interests = {
            interest.name.casefold(): interest
            for interest in getattr(self.profile, "interests", [])
            if interest.verified and interest.allowed_in_cv and interest.enabled
        }
        clean_interests = []
        selected_interest_ids = []
        if draft.interests:
            for item in draft.interests:
                canonical = allowed_interests.get(item.casefold())
                if canonical and canonical.name not in clean_interests:
                    clean_interests.append(canonical.name)
                    selected_interest_ids.append(canonical.id)
                elif not canonical:
                    warnings.append(f"Unsupported interest removed: {item}")
        else:
            for interest in allowed_interests.values():
                if interest.name not in clean_interests:
                    clean_interests.append(interest.name)
                    selected_interest_ids.append(interest.id)

        draft.interests = clean_interests
        draft.selected_interest_ids = selected_interest_ids

        cert_lookup = {item.name.casefold(): item for item in self.profile.certifications}
        clean_certs = []
        for cert in draft.certifications:
            if cert.name.casefold() not in cert_lookup:
                warnings.append(f"Unsupported AI fact removed: {cert.name}")
                continue
            clean_certs.append(ResumeCertification(**cert_lookup[cert.name.casefold()].model_dump()))
        draft.certifications = clean_certs
        warnings.extend(self._coverage_warnings(draft, job))
        for project in draft.projects:
            from app.services.content_quality import deduplicate_project_text
            project.description = deduplicate_project_text(project.description)
        for experience in draft.experience:
            experience.bullets = deduplicate_bullets(experience.bullets)
        warnings.extend(quality_issues(draft, self.profile))
        if not preserve_skills and job.workflow == 'job':
            from app.services.content_quality import editorial_review_issues
            def relevant(entry):
                priority, topical, overlap, _ = self._entry_relevance(entry, job)
                return bool(priority or topical or overlap >= 2)

            warnings.extend(dict.fromkeys(editorial_review_issues(
                draft, self.catalog, relevant=relevant)))
        return ValidationResult(resume=draft, warnings=warnings)

    @staticmethod
    def _experience_wording(text: str) -> str:
        # A supported troubleshooting activity does not establish ownership or
        # administration. This is a bounded edit, not arbitrary paraphrasing.
        return re.sub(r"^Supported (.+) troubleshooting[.]$", r"Assisted with \1 troubleshooting.", text)

    def _project_description(self, source, job: JobRequest, *, summary: str = '') -> str:
        return self._project_content(source, job, summary=summary)[0]

    def _project_content(self, source, job: JobRequest, *, summary: str = '') -> tuple[str, list[str]]:
        from app.services.content_quality import deduplicate_project_text, project_sentences
        from app.services.professional_summary import summary_contains_clause
        entries = [e for e in self.catalog.prompt_entries if e.kind == 'project'
                     and e.owner_name == source.name and (':fact:' in e.source_id or ':description:' in e.source_id)]
        ranked = sorted(entries, key=lambda e: self._entry_relevance(e, job), reverse=True)
        relevant = any((relevance[0] > 0 or relevance[1] >= 2 or relevance[2] >= 2)
                       for e in entries if (relevance := self._entry_relevance(e, job)))
        level = job.tailoring_level
        sentence_budget = round((1 - level) * (5 if relevant else 2) + level * 3)
        char_budget = round((1 - level) * (1100 if relevant else 450) + level * 700)
        # Keep the goal/context first, then methods and evaluation from this owner.
        # Context need not repeat a literal posting keyword to be useful.
        ranked.sort(key=lambda e: ':description:' not in e.source_id)
        candidates = [(sentence, entry.source_id) for entry in ranked
                      for sentence in project_sentences(entry.text)]
        focus = self._target(job)
        alternatives = [(sentence, source_id) for sentence, source_id in candidates
                        if not summary_contains_clause(summary, sentence)
                        or (focus.evidence_led and ':description:' in source_id
                            and re.search(r'\b(?:personal|academic|homelab|home lab|thesis|coursework)\b', sentence, re.I))]
        if alternatives:
            # A short comparison/evaluation clause may carry the only academic
            # qualifier. Keep it when the cleanup can fuse it with the purpose,
            # instead of losing thesis provenance to cross-section deduplication.
            for item in candidates:
                if item not in alternatives and any(
                        len(deduplicate_project_text(other[0] + ' ' + item[0]))
                        < len(other[0] + ' ' + item[0]) for other in alternatives):
                    alternatives.append(item)
            candidates = alternatives
        selected = []
        selected_ids = []
        for sentence, source_id in candidates:
            if sentence in selected:
                continue
            candidate = deduplicate_project_text(' '.join([*selected, self._complete_sentence(sentence)]))
            if len(candidate) <= char_budget or not selected:
                selected = project_sentences(candidate)
                selected_ids.append(source_id)
            if len(selected) >= sentence_budget:
                break
        return deduplicate_project_text(' '.join(selected)), list(dict.fromkeys(selected_ids))

    def _coverage_warnings(self, resume: TailoredResume, job: JobRequest) -> list[str]:
        """Compare confirmed employer requirements against actual exported content.

        Missing coverage creates a review message; it never manufactures a skill
        or converts an incomplete requirement into a candidate qualification.
        """
        from app.models.candidate import Education, Experience, Project
        from app.models.job import RequirementStatus
        from app.services.evidence_matching import EvidenceMatcher
        from app.services.job_sections import extract_sections
        from app.services.languages import profile_languages

        visible = self.profile.model_copy(deep=True)
        visible.summary_facts = [resume.professional_summary] if resume.professional_summary else []
        visible.skills = {"technical": resume.core_skills, "languages": profile_languages(self.profile)}
        source_employment = {(e.company, e.title): e for e in self.profile.experience}
        visible.experience = []
        for e in resume.experience:
            source = source_employment.get((e.company, e.title))
            if source:
                visible.experience.append(Experience(company=e.company, title=e.title, start=source.start,
                    end=source.end, facts=[b.text for b in e.bullets]))
        visible.projects = [Project(name=p.name, description=p.description, technologies=p.technologies)
                            for p in resume.projects]
        visible.education = [Education(institution=e.institution, qualification=e.qualification, dates=e.dates,
            facts=[value for value in (e.specialisation, e.thesis_subline) if value]) for e in resume.education]
        actual = EvidenceMatcher(FactCatalog(visible))
        full = EvidenceMatcher(self.catalog, self.skills_bank)
        warnings, seen = [], set()
        units, _ = extract_sections(job.job_description)
        for unit in units:
            if unit.category not in {"mandatory", "preferred"} or unit.name in seen:
                continue
            seen.add(unit.name)
            confirmed = full.match(unit.name, alternatives=unit.alternatives, operator=unit.operator)
            shown = actual.match(unit.name, alternatives=unit.alternatives, operator=unit.operator)
            if (confirmed and confirmed.status == RequirementStatus.STRONG
                    and (not shown or shown.status != RequirementStatus.STRONG)):
                warnings.append(f"Confirmed requirement needs CV coverage review: {unit.quote}")
        return warnings

    def _experience_entries(self, index: int, job: JobRequest):
        entries = [e for e in self.catalog.prompt_entries if e.kind == "experience" and e.owner_index == index
                   and ':fact:' in e.source_id]
        if job.workflow == 'job' and job.tailoring_level < 1 and self._target(job).evidence_led:
            entries = [e for e in entries if not generic_duty(e.text)] or entries
        ranked = sorted(entries, key=lambda e: self._entry_relevance(e, job), reverse=True)
        relevant = sum(any(self._entry_relevance(e, job)[:3]) for e in entries)
        target = min(4, relevant) if relevant else (2 if index == 0 else 1)
        budget = round((1 - job.tailoring_level) * target + job.tailoring_level * min(4, len(entries)))
        return ranked[:budget]

    def _rank_bullets(self, bullets, job):
        if job.tailoring_level == 1:
            order = {e.source_id: i for i, e in enumerate(self.catalog.prompt_entries)}
            return sorted(bullets, key=lambda b: min(order[i] for i in b.source_fact_ids))
        focus = self._target(job)
        if job.workflow == 'job' and focus.evidence_led:
            bullets = [b for b in bullets if not generic_duty(b.text)] or bullets

        def rank(b):
            entries = self.catalog.valid(b.source_fact_ids, kind='experience')
            relevance = max((self._entry_relevance(e, job) for e in entries), default=(0, 0, 0, 0))
            return (
                not generic_duty(b.text),
                relevance,
                evidence_specificity(b.text),
            )

        ranked = sorted(((rank(b), b) for b in bullets), key=lambda item: item[0], reverse=True)
        if job.workflow == 'job' and focus.evidence_led:
            # Do not fill unused bullet slots with tangential model selections.
            matching = [b for quality, b in ranked if any(quality[1][:3])]
            if matching:
                return matching
        return [b for _, b in ranked]

    def _lacks_source_detail(self, entry, bullets, job):
        return (job.workflow == 'job' and job.tailoring_level < 1
                and any(self._entry_relevance(entry, job)[:3]) and high_value_detail(entry.text)
                and any(entry.source_id in b.source_fact_ids for b in bullets)
                and not any(entry.source_id in b.source_fact_ids and high_value_detail(b.text)
                            and scope_mentions(entry.text) <= scope_mentions(b.text)
                            and set(re.findall(r'\d+(?:[.,]\d+)?', entry.text))
                            <= set(re.findall(r'\d+(?:[.,]\d+)?', b.text))
                            for b in bullets))

    def _target(self, job: JobRequest) -> TargetFocus:
        key = (job.role, job.relevance_text, job.workflow)
        if self._focus_cache is None or self._focus_cache[0] != key:
            self._focus_cache = (key, target_focus(job.role, job.relevance_text if job.workflow == 'job' else '',
                                                   self.analysis))
        return self._focus_cache[1]

    def _entry_relevance(self, entry, job: JobRequest) -> tuple[float, float, float, float]:
        focus = self._target(job)
        terms = focus.terms if focus.evidence_led else self._posting_terms(job)
        # The LLM's cited match evidence supplies the primary ordering; literal
        # overlap is only a fallback/tiebreaker, never proof of competence.
        overlap = normalized_tokens(entry.text) & terms
        if job.tailoring_level == 1:  # Source-order endpoint.
            return (0, 0, 0, 0)
        priority = self.fact_priorities.get(entry.source_id, 0)
        topical = focus.score(entry.text)
        specificity = evidence_specificity(entry.text) if entry.kind == 'experience' and job.workflow == 'job' else 0
        lexical = min(len(overlap), 4)
        # Prefer a documented scope/result within the same job theme without
        # allowing a number or generic metric to manufacture relevance.
        if focus.evidence_led and entry.kind == 'experience' and job.workflow == 'job':
            direct = min(len(focus.direct_terms(entry.text)), 4)
            if not priority and not direct:
                return (0, 0, 0, specificity)
            topical = (topical / 4) + direct
            topical += 1.0 if specificity >= 2 and (topical or lexical >= 2) else 0
        return (priority, topical, lexical, specificity)

    def _posting_terms(self, job: JobRequest) -> set[str]:
        from app.services.job_sections import relevance_text

        role, text = job.role, job.relevance_text
        if self._posting_cache is None or self._posting_cache[:2] != (role, text):
            self._posting_cache = (role, text, normalized_tokens(relevance_text(f"{role}\n{text}")))
        return self._posting_cache[2]

    def _direction_headline(self, occupation, skills, job):
        if normalized_tokens(job.role) <= normalized_tokens(occupation):
            return occupation
        focus = self._target(job)
        terms = focus.terms
        relevant = [s for s in skills if focus.score(s) or normalized_tokens(s) & terms]
        relevant.sort(key=lambda s: (len(normalized_tokens(s) & terms), focus.score(s))
                      if focus.evidence_led else (focus.score(s), len(normalized_tokens(s) & terms)), reverse=True)
        if not relevant:
            return occupation
        if focus.family == 'data_science':
            python = next((s for s in relevant if re.fullmatch(r'(?:Basic |Junior )?Python', s)), None)
            if python:
                relevant.remove(python)
                relevant.insert(0, python)
        # Whole, eligible labels retain Basic/Junior qualifiers. No target title
        # or invented "ML Engineer" occupation is ever composed here.
        if len(relevant) > 1:
            value = f'{relevant[0]} & {relevant[1]} | {occupation}'
            if len(value) <= 100:
                return value
        value = f'{relevant[0]} | {occupation}'
        return value if len(value) <= 140 else occupation

    def _section_order(self, job):
        original = ['summary', 'skills', 'learning', 'languages', 'experience', 'education',
                    'projects', 'certifications', 'interests']
        target = list(original)
        project_score = max((sum(self._entry_relevance(e, job)[:3]) for e in self.catalog.prompt_entries
                             if e.kind == 'project'), default=0)
        experience_score = max((sum(self._entry_relevance(e, job)[:3]) for e in self.catalog.prompt_entries
                                if e.kind == 'experience'), default=0)
        focus = self._target(job)
        employment_first = focus.family in {'support', 'production_support', 'implementation', 'integration_support',
                                            'system_administration'} or focus.professional_required
        if project_score > experience_score and not (employment_first and self.profile.experience):
            leading = ['summary', 'skills', 'projects']
            if focus.family == 'data_science' and self.profile.education:
                leading.append('education')
            target = leading + [s for s in original if s not in leading]
        else:
            target = ['summary', 'skills', 'experience'] + [s for s in original
                                                         if s not in {'summary', 'skills', 'experience'}]
        level = job.tailoring_level
        # Keep offer-specific narrative visible at the midpoint. A raw 50/50
        # positional average puts sidebar-only sections ahead of the strongest
        # evidence and can reverse the intended Projects/Experience order.
        weight = level ** 2
        return sorted(original, key=lambda s: (1 - weight) * target.index(s) + weight * original.index(s))

    def _build_headline(self, role: str, selected_ids: list[str], core_skills: list[str]) -> str:
        # A target advertisement cannot confer a new occupation or seniority.
        # Use the real occupation, without a list of unrelated selected skills.
        if not self.profile.experience:
            return "Professional Profile"
        title = self.profile.experience[0].title.strip()
        title = re.sub(r"\bTier\s*([123])\b", r"L\1", title, flags=re.I)
        return title[:140]

    @staticmethod
    def _is_complete_summary(value: str) -> bool:
        text = value.strip()
        if not text or text[-1] not in ".!?" or text.count("(") != text.count(")"):
            return False
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        if any(len(re.findall(r"[\w'-]+", sentence)) < 4 for sentence in sentences):
            return False
        hanging = re.compile(r"\b(?:and|or|including|such as|cross-tier|cross-functional)[.!?]$", re.I)
        return not any(hanging.search(sentence) for sentence in sentences)

    @staticmethod
    def _complete_sentence(value: str) -> str:
        text = value.strip()
        return text if not text or text[-1] in ".!?" else f"{text}."

    def _project_relevance(self, project: ResumeProject, job: JobRequest) -> int:
        job_tokens = self._posting_terms(job)
        role_tokens = normalized_tokens(job.role)
        generic = {
            "built",
            "control",
            "data",
            "hands",
            "human",
            "job",
            "large",
            "pipeline",
            "project",
            "review",
            "services",
            "source",
            "that",
            "using",
            "workflows",
        }
        profile_projects = {p.name.casefold(): p for p in self.profile.projects}
        source = profile_projects.get(project.name.casefold())
        technologies = source.technologies if source else project.technologies
        facts = source.facts if source else [project.description]
        tech_tokens = normalized_tokens(" ".join(technologies))
        fact_tokens = normalized_tokens(" ".join(facts)) - generic
        tech_role_overlap = len(role_tokens & tech_tokens)
        tech_job_overlap = len(job_tokens & tech_tokens)
        fact_overlap = len(job_tokens & fact_tokens)
        focus = self._target(job).score(' '.join([source.description, *facts] if source else facts))
        return 100 * focus + 8 * tech_role_overlap + 4 * tech_job_overlap + 2 * fact_overlap

    def _rank_projects(self, projects: list[ResumeProject], job: JobRequest) -> list[ResumeProject]:
        profile_projects = {project.name.casefold(): project for project in self.profile.projects}

        def score(project: ResumeProject) -> tuple[int, float, int]:
            source = profile_projects.get(project.name.casefold())
            technologies = source.technologies if source else project.technologies
            relevance = self._project_relevance(project, job)
            evidence_priority = max((self.fact_priorities.get(i, 0) for i in project.source_fact_ids), default=0)
            return relevance, evidence_priority, len(technologies)

        ranked = sorted(projects, key=score, reverse=True)
        original = {p.name.casefold(): i for i, p in enumerate(self.profile.projects)}
        target = {p.name.casefold(): i for i, p in enumerate(ranked)}
        weight = job.tailoring_level ** 2
        return sorted(ranked, key=lambda p: (1 - weight) * target[p.name.casefold()]
                      + weight * original.get(p.name.casefold(), len(original)))
