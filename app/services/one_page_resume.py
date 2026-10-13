"""Select concise, cited content for new CVs; never rewrite manual edits."""
import re
from copy import deepcopy

from app.services.fact_catalog import normalized_tokens


def _bullet_key(text):
    value = text.casefold()
    value = re.sub(r'\b(?:microsoft|ms)\s+sql\s+server\b', 'sql', value)
    value = re.sub(r'\bt[- ]sql\b', 'tsql', value)
    value = re.sub(r'\bqueries\b', 'query', value)
    tokens = normalized_tokens(value)
    if {'sql', 'tsql'} <= tokens:
        return (tokens - {'used', 'operational', 'query'}) | set(re.findall(r'\b\d+\b', value))
    return {value.strip()}


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
        retained = []
        for index, bullet in enumerate(experience.bullets):
            key = _bullet_key(bullet.text)
            redundant = any(index != j and key and key <= _bullet_key(other.text)
                and (key != _bullet_key(other.text) or index > j)
                for j, other in enumerate(experience.bullets))
            if redundant and not protected_item(bullet.source_fact_ids):
                actions.append(f'One-page selection: omitted repeated bullet in {experience.company}.')
            else:
                retained.append(bullet)
        experience.bullets = retained
    if fits(draft):
        return draft, actions

    entries = [e for e in validator.catalog.valid(draft.summary_source_fact_ids)
               if e.kind in {'summary', 'experience', 'project'}
               and (e.kind == 'summary' or ':fact:' in e.source_id)]
    # Prefer identity first; the remaining sentence supplies relevant evidence.
    entries.sort(key=lambda e: (e.kind != 'summary', tuple(-v for v in rank(e.text, [e.source_id]))))
    selected = []
    for entry in entries:
        if len(entry.text) <= 240 and sum(len(e.text) + 1 for e in selected) + len(entry.text) <= 330:
            selected.append(entry)
        if len(selected) == 2:
            break
    missing_protected_summary = protected.intersection(draft.summary_source_fact_ids) - {e.source_id for e in selected}
    if selected and not missing_protected_summary and len(' '.join(e.text for e in selected)) < len(draft.professional_summary):
        draft.professional_summary = ' '.join(e.text for e in selected)
        draft.summary_source_fact_ids = [e.source_id for e in selected]
        draft.summary_attestation = ''
        actions.append('One-page selection: summary reduced to at most two exact source facts.')
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
