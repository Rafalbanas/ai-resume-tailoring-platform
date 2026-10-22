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
from app.services.fact_catalog import FactCatalog, normalized_tokens
from app.services.languages import is_language_skill
from app.services.professional_summary import build_summary, deduplicate_summary
from app.services.skills_bank import GENERATED_CV_SKILL_TARGET, SkillsBank


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
        if analysis:
            for position, requirement in enumerate([*analysis.requirements, *analysis.role_competencies]):
                if requirement.status not in {'strong', 'partial'}:
                    continue
                # Preserve the model's ordering within the same priority rather
                # than allowing a long, generic citation to dominate the summary.
                weight = (3 if requirement.priority == 'mandatory' else 1) / (1 + position * 0.05)
                for source_id in requirement.source_fact_ids:
                    self.fact_priorities[source_id] = max(weight, self.fact_priorities.get(source_id, 0))
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
                            if self.catalog.get(evidence.source_id) and self.skills_bank.evidence_supports(skill, evidence):
                                self.fact_priorities[evidence.source_id] = max(weight, self.fact_priorities.get(evidence.source_id, 0))

    def validate_manual_edit(self, original: TailoredResume, edited: TailoredResume, job: JobRequest, *, allow_manual_skills: bool = False):
        from app.services.resume_edit_validation import validate_manual_edit
        return validate_manual_edit(self, original, edited, job, allow_manual_skills=allow_manual_skills)

    def validate(self, candidate: TailoredResume, job: JobRequest, *, preserve_skills: bool = False) -> ValidationResult:
        from app.services.cv_content_policy import cv_catalog
        self.catalog = cv_catalog(self.profile, job)
        draft = deepcopy(candidate)
        warnings: list[str] = []
        learning = self.skills_bank.learning_for_job(f"{job.role}\n{job.job_description}") if self.skills_bank else []
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
                f"{job.role}\n{job.job_description}",
                minimum=0 if preserve_skills else GENERATED_CV_SKILL_TARGET,
                maximum=16,
                requested_only=preserve_skills,
            )
            if self.fact_priorities and not preserve_skills:
                requested_order = {i: rank for rank, i in enumerate(dict.fromkeys(requested_ids))}
                selected.sort(key=lambda s: (
                    s.id not in requested_order, requested_order.get(s.id, len(requested_order)),
                    -max((self.fact_priorities.get(i, 0) for i in [f'skill:{s.id}', *(e.source_id for e in s.evidence)]), default=0)))
            draft.selected_skill_ids = [skill.id for skill in selected]
            draft.core_skills = [self.skills_bank.wording(skill) for skill in selected]
            allowed_skills = {
                skill_key(alias): self.skills_bank.wording(skill)
                for skill in self.skills_bank.skills
                if self.skills_bank.eligible(skill)
                for alias in self.skills_bank.aliases_for(skill)
            }
        else:
            for skill in draft.core_skills:
                key = skill_key(skill)
                if key in allowed_skills:
                    canonical = allowed_skills[key]
                    if canonical not in clean_skills:
                        clean_skills.append(canonical)
                else:
                    warnings.append(f"Unsupported AI fact removed: {skill}")
            if not clean_skills and not preserve_skills:
                job_text = job.job_description.casefold()
                relevant = [
                    canonical
                    for key, canonical in allowed_skills.items()
                    if key and (key in job_text or canonical.casefold() in job_text)
                ]
                clean_skills = relevant
            if not preserve_skills and len(clean_skills) < GENERATED_CV_SKILL_TARGET:
                job_tokens = normalized_tokens(f"{job.role}\n{job.job_description}")
                remaining = sorted(dict.fromkeys(allowed_skills.values()),
                                   key=lambda value: -len(normalized_tokens(value) & job_tokens))
                for value in remaining:
                    if value not in clean_skills:
                        clean_skills.append(value)
                    if len(clean_skills) >= GENERATED_CV_SKILL_TARGET:
                        break
            draft.core_skills = clean_skills[:18]

        verified_headline = self._build_headline(job.role, draft.selected_skill_ids, draft.core_skills)
        # Accept a model-selected direction only as exact eligible skill wording
        # after the real occupation. A target job never confers a new title.
        pieces = [s.strip() for s in draft.headline.split('|')]
        pieces[0] = re.sub(r'\bTier\s*([123])\b', r'L\1', pieces[0], flags=re.I)
        if len(pieces) == 2 and pieces[0] == verified_headline and pieces[1] in draft.core_skills:
            verified_headline = pieces[0] + ' | ' + pieces[1]
        elif len(pieces) == 2 and pieces[0] == verified_headline:
            suffixes = pieces[1].split(' · ')
            if 1 <= len(suffixes) <= 2 and all(s in draft.core_skills for s in suffixes):
                verified_headline = pieces[0] + ' | ' + pieces[1]
        if self.analysis is not None and draft.headline.strip() == job.role.strip() and draft.headline.strip() != verified_headline:
            # A rejected advertised title can still communicate direction through
            # exact, already eligible skill labels selected by the model.
            suffix = ' · '.join(draft.core_skills[:2])
            if suffix and len(verified_headline + ' | ' + suffix) <= 140:
                verified_headline += ' | ' + suffix
        if draft.headline.strip() and draft.headline.strip() not in {job.role.strip(), verified_headline}:
            warnings.append("Unsupported or non-deterministic headline was replaced with verified role and skills")
        draft.headline = verified_headline

        summary, summary_ids = build_summary(self.catalog, f"{job.role}\n{job.job_description}", priorities=self.fact_priorities)
        summary_entries = self.catalog.valid(draft.summary_source_fact_ids)
        model_ids = [e.source_id for e in summary_entries if e.kind in {"summary", "experience", "project"}
                     and (e.kind == "summary" or ":fact:" in e.source_id)]
        sentence_count = len(re.split(r"(?<=[.!?])\s+(?=[A-Z])", draft.professional_summary.strip()))
        from app.services.content_quality import deduplicate_bullets, deduplicate_text, quality_issues, unfinished
        from app.services.cv_content_policy import internal_annotation
        from app.services.summary_review import sign_source_summary, sign_summary, valid_summary_attestation
        reviewed = (all(self.catalog.get(i) for i in draft.summary_source_fact_ids)
                    and not internal_annotation(draft.professional_summary)
                    and valid_summary_attestation(draft, self.profile, self.review_key))
        if reviewed:
            model_ids = [e.source_id for e in summary_entries]
        if (unfinished(draft.professional_summary) or (sentence_count > 5 and not reviewed)
                or not (reviewed or self.catalog.supports_paraphrase(draft.professional_summary, model_ids))):
            if draft.professional_summary != summary:
                warnings.append("Professional summary rebuilt from concise verified source sentences; model tone cannot be assessed from this replacement")
            draft.professional_summary = summary
            draft.summary_source_fact_ids = summary_ids
            draft.summary_attestation = ''
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
            if self.fact_priorities and not preserve_skills:
                cited = {i for b in bullets for i in b.source_fact_ids}
                for entry in self._experience_entries(exp_index, job):
                    if self.fact_priorities.get(entry.source_id, 0) and entry.source_id not in cited:
                        bullets.append(ResumeBullet(text=self._experience_wording(entry.text), source_fact_ids=[entry.source_id]))
                bullets.sort(key=lambda b: max((self.fact_priorities.get(i, 0) for i in b.source_fact_ids), default=0), reverse=True)
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
                existing.bullets = deduplicate_bullets(existing.bullets + [bullet for bullet in item.bullets if bullet.text not in known])[:4]
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
            canonical_description = self._project_description(source, job)
            attested_descriptions = {source.description, *source.facts}
            attested_descriptions.add(canonical_description)
            if project.description not in attested_descriptions:
                warnings.append(f"Project wording replaced with verified description: {project.name}")
            if project.description not in attested_descriptions:
                project.description = canonical_description
            elif self.fact_priorities and project.description == source.description and not preserve_skills:
                project.description = canonical_description
            project.source_fact_ids = [entry.source_id for entry in self.catalog.prompt_entries
                if entry.kind == "project" and entry.owner_index == index and ":technology:" not in entry.source_id]
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
            if content:
                clean_projects.append(
                    ResumeProject(
                        name=source.name,
                        url=source.url if source.url.startswith(("https://", "http://")) else "",
                        description=self._project_description(source, job),
                        technologies=[
                            tech
                            for tech in source.technologies
                            if skill_key(tech) in allowed_skills
                        ],
                        source_fact_ids=[entry.source_id for entry in entries if ":technology:" not in entry.source_id],
                    )
                )
        ranked_projects = self._rank_projects(clean_projects, job)
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
            project.description = deduplicate_text(project.description)
        for experience in draft.experience:
            experience.bullets = deduplicate_bullets(experience.bullets)
        warnings.extend(quality_issues(draft, self.profile))
        return ValidationResult(resume=draft, warnings=warnings)

    @staticmethod
    def _experience_wording(text: str) -> str:
        # A supported troubleshooting activity does not establish ownership or
        # administration. This is a bounded edit, not arbitrary paraphrasing.
        return re.sub(r"^Supported (.+) troubleshooting[.]$", r"Assisted with \1 troubleshooting.", text)

    def _project_description(self, source, job: JobRequest) -> str:
        entries = [e for e in self.catalog.prompt_entries if e.kind == 'project'
                   and e.owner_name == source.name and (':fact:' in e.source_id or ':description:' in e.source_id)]
        ranked = sorted(entries, key=lambda e: self._entry_relevance(e, job), reverse=True)
        selected = []
        for entry in ranked:
            if not any(self._entry_relevance(entry, job)):
                continue
            if entry.text.strip() and entry.text not in selected:
                candidate = ' '.join([*selected, entry.text])
                if len(candidate) <= 500 or not selected:
                    selected.append(self._complete_sentence(entry.text))
            if len(selected) == 2:
                break
        from app.services.content_quality import deduplicate_text
        return deduplicate_text(' '.join(selected) or source.description or ' '.join(source.facts[:2]))

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
        return sorted(entries, key=lambda e: self._entry_relevance(e, job), reverse=True)[:4]

    def _entry_relevance(self, entry, job: JobRequest) -> tuple[float, int]:
        from app.services.job_sections import relevance_text
        terms = normalized_tokens(relevance_text(f'{job.role}\n{job.job_description}'))
        # The LLM's cited match evidence supplies the primary ordering; literal
        # overlap is only a fallback/tiebreaker, never proof of competence.
        overlap = normalized_tokens(entry.text) & terms
        return self.fact_priorities.get(entry.source_id, 0), len(overlap)

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
        from app.services.job_sections import relevance_text
        job_tokens = normalized_tokens(relevance_text(f"{job.role}\n{job.job_description}"))
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
        return 8 * tech_role_overlap + 4 * tech_job_overlap + 2 * fact_overlap

    def _rank_projects(self, projects: list[ResumeProject], job: JobRequest) -> list[ResumeProject]:
        profile_projects = {project.name.casefold(): project for project in self.profile.projects}

        def score(project: ResumeProject) -> tuple[float, int, int]:
            source = profile_projects.get(project.name.casefold())
            technologies = source.technologies if source else project.technologies
            relevance = self._project_relevance(project, job)
            evidence_priority = max((self.fact_priorities.get(i, 0) for i in project.source_fact_ids), default=0)
            return evidence_priority, relevance, len(technologies)

        return sorted(projects, key=score, reverse=True)

