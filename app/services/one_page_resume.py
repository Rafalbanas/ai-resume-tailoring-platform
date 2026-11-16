"""Select concise, cited content for new CVs; never rewrite manual edits."""
from copy import deepcopy

from app.services.content_quality import deduplicate_bullets
from app.services.fact_catalog import normalized_tokens


def prefer_one_page(resume, validator, job_text, fits, *, known_overflow=False):
    """Prefer one page, omitting only optional detail, with a full-CV fallback.

    Unlike the explicit legacy hard fit, retain the complete validated summary,
    the strongest relevant project, employment identities, education and learning status.
    Test every single omission; never collapse all projects before measuring.
    """
    draft = deepcopy(resume)
    actions = []
    protected = set()
    if validator.analysis:
        for requirement in [*validator.analysis.requirements, *validator.analysis.role_competencies]:
            if requirement.priority == 'mandatory' and requirement.status in {'strong', 'partial'}:
                for source_id in requirement.source_fact_ids:
                    entry = validator.catalog.get(source_id)
                    protected.add(entry.source_id if entry else source_id)
                    if validator.skills_bank:
                        skill = validator.skills_bank.get(source_id.removeprefix('skill:'))
                        skill = skill or (validator.skills_bank.find(entry.text)
                                          if entry and entry.kind == 'skill' else None)
                        if skill and validator.skills_bank.eligible(skill):
                            for evidence in skill.evidence:
                                if validator.skills_bank.evidence_supports(skill, evidence):
                                    resolved = validator.catalog.get(evidence.source_id)
                                    protected.add(resolved.source_id if resolved else evidence.source_id)
    terms = normalized_tokens(job_text)
    from app.services.role_focus import role_focus_score

    def utility(text, ids):
        return (max((validator.fact_priorities.get(i, 0) for i in ids), default=0),
                role_focus_score(text, job_text), len(normalized_tokens(text) & terms))

    if not known_overflow and fits(draft):
        return draft, actions
    while True:
        options = []
        for i, experience in enumerate(draft.experience):
            if len(experience.bullets) > 1:
                for j, bullet in enumerate(experience.bullets):
                    if not protected.intersection(bullet.source_fact_ids):
                        options.append((utility(bullet.text, bullet.source_fact_ids), -i, 'bullet', i, j))
        # Keep the strongest relevant project intact; it may be the only
        # evidence for a career transition. An unrelated first project is not
        # more important than relevant commercial duties merely by being first.
        first_utility = (utility(draft.projects[0].description, draft.projects[0].source_fact_ids)
                         if draft.projects else (0, 0, 0))
        keep_first = first_utility[0] > 0 or first_utility[1] > 0 or first_utility[2] >= 2
        start = 1 if keep_first else 0
        for i, project in enumerate(draft.projects[start:], start=start):
            if not protected.intersection(project.source_fact_ids):
                options.append((utility(project.description, project.source_fact_ids), -i, 'project', i, 0))
        # Keep a useful skills panel; remove only non-matching lower-priority
        # entries, never a required skill or its Basic/Junior qualifier.
        if len(draft.core_skills) > 10:
            for i, wording in enumerate(draft.core_skills):
                skill = validator.skills_bank.find(wording) if validator.skills_bank else None
                ids = ([f'skill:{skill.id}', *(
                    entry.source_id if (entry := validator.catalog.get(e.source_id)) else e.source_id
                    for e in skill.evidence)] if skill else [])
                direct = (validator.skills_bank.mentioned(skill, job_text) if skill else
                          bool(normalized_tokens(wording) & terms))
                if not direct and not protected.intersection(ids):
                    options.append((utility(wording, ids), -i, 'skill', i, 0))
        if draft.interests:
            options.append(((-1, -1, -1), 0, 'interests', 0, 0))
        if not options:
            break
        _, _, kind, i, j = min(options)
        if kind == 'bullet':
            owner = draft.experience[i]
            owner.bullets.pop(j)
            actions.append(f'Preferred one-page selection: omitted optional detail in {owner.company}.')
        elif kind == 'project':
            project = draft.projects.pop(i)
            actions.append(f'Preferred one-page selection: omitted lower-priority project {project.name}.')
        elif kind == 'skill':
            original_count = len(draft.core_skills)
            draft.core_skills.pop(i)
            if len(draft.selected_skill_ids) == original_count:
                draft.selected_skill_ids.pop(i)
            actions.append('Preferred one-page selection: omitted an unrelated lower-priority skill.')
        else:
            draft.interests = []
            draft.selected_interest_ids = []
            actions.append('Preferred one-page selection: omitted optional interests.')
        if fits(draft):
            return draft, actions
    # Do not silently weaken the only substantive project or mandatory evidence
    # to achieve a nominal one-page success. Discard all trial omissions.
    return deepcopy(resume), ['Preferred one-page selection: important evidence requires a complete multi-page CV; optional details retained.']


def select_one_page(resume, validator, job_text, fits):
    """Omit lower-priority details, preserving citations and mandatory evidence."""
    draft = deepcopy(resume)
    actions = []
    protected = set()
    if validator.analysis:
        for requirement in [*validator.analysis.requirements, *validator.analysis.role_competencies]:
            if requirement.priority == 'mandatory' and requirement.status in {'strong', 'partial'}:
                protected.update(requirement.source_fact_ids)
                protected.update(entry.source_id for source_id in requirement.source_fact_ids
                                 if (entry := validator.catalog.get(source_id)) is not None)
    priorities = validator.fact_priorities
    tokens = normalized_tokens(job_text)

    def protected_item(ids):
        return bool(protected.intersection(ids))

    def rank(text, ids=()):
        return (max((priorities.get(i, 0) for i in ids), default=0),
                len(normalized_tokens(text) & tokens), -len(text))

    for experience in draft.experience:
        retained = deduplicate_bullets(experience.bullets)
        if len(retained) < len(experience.bullets):
            actions.append(f'One-page selection: consolidated repeated bullet in {experience.company}; source citations retained.')
        experience.bullets = retained
    if fits(draft):
        return draft, actions

    entries = [e for e in validator.catalog.valid(draft.summary_source_fact_ids)
               if e.kind in {'summary', 'experience', 'project'}
               and (e.kind == 'summary' or ':fact:' in e.source_id)]
    # Prefer identity first; the remaining sentence supplies relevant evidence.
    entries.sort(key=lambda e: (e.kind != 'summary', tuple(-v for v in rank(e.text, [e.source_id]))))
    # Required facts take precedence over the normal two-fact preference.
    # Several short facts can fit the same length budget without losing evidence.
    selected = [entry for entry in entries if entry.source_id in protected]
    if len(' '.join(entry.text for entry in selected)) > 330:
        selected = []  # Keep the original summary if required evidence is too long.
    else:
        for entry in entries:
            if len(selected) >= 2:
                break
            if entry in selected:
                continue
            if len(entry.text) <= 240 and sum(len(e.text) + 1 for e in selected) + len(entry.text) <= 330:
                selected.append(entry)
    missing_protected_summary = protected.intersection(draft.summary_source_fact_ids) - {e.source_id for e in selected}
    if selected and not missing_protected_summary and len(' '.join(e.text for e in selected)) < len(draft.professional_summary):
        draft.professional_summary = ' '.join(e.text for e in selected)
        draft.summary_source_fact_ids = [e.source_id for e in selected]
        draft.summary_attestation = ''
        actions.append('One-page selection: concise exact source facts retained, including all mandatory summary evidence.')
    for project in draft.projects:
        entries = [e for e in validator.catalog.valid(project.source_fact_ids, kind='project')
                   if ':fact:' in e.source_id and len(e.text) <= 260]
        entries.sort(key=lambda e: rank(e.text, [e.source_id]), reverse=True)
        visible_protected = {e.source_id for e in entries if e.source_id in protected and e.text in project.description}
        if entries and visible_protected <= {entries[0].source_id} and len(entries[0].text) < len(project.description):
            project.description = entries[0].text
            # Keep only the citations which actually support the visible fact.
            project.source_fact_ids = [entries[0].source_id]
            actions.append(f'One-page selection: concise verified description for {project.name}.')
    if fits(draft):
        return draft, actions
    if draft.interests:
        draft.interests = []
        draft.selected_interest_ids = []
        actions.append('One-page selection: omitted optional interests.')
        if fits(draft):
            return draft, actions
    # All employment owners/dates and education stay. Never omit protected bullets.
    while True:
        options = [(rank(b.text, b.source_fact_ids), i, j)
                   for i, e in enumerate(draft.experience) if len(e.bullets) > 1
                   for j, b in enumerate(e.bullets) if not protected_item(b.source_fact_ids)]
        if not options:
            break
        _, i, j = min(options)
        draft.experience[i].bullets.pop(j)
        actions.append(f'One-page selection: omitted lower-priority detail in {draft.experience[i].company}.')
        if fits(draft):
            return draft, actions
    while len(draft.projects) > 1:
        options = [(rank(p.description, p.source_fact_ids), i) for i, p in enumerate(draft.projects)
                   if not protected_item(p.source_fact_ids)]
        if not options:
            break
        _, i = min(options)
        project = draft.projects.pop(i)
        actions.append(f'One-page selection: omitted lower-priority project {project.name}.')
        if fits(draft):
            return draft, actions
    raise ValueError('Modern Sidebar could not fit one page while keeping employment history, education, learning status and mandatory evidence. Select ATS Classic for the complete CV or shorten optional content in the editor.')
