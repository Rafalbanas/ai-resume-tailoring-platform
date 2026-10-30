"""Constrain selections without empty enums or cross-owner citations."""

from copy import deepcopy


def choices(array, values, minimum=0):
    values = list(dict.fromkeys(values))
    if values:
        array["items"] = {"type": "string", "enum": values}
        array["minItems"] = minimum
    else:
        array.clear()
        array.update(type="array", items={"type": "string"}, maxItems=0)


def resume_schema(schema, catalog, skills, skill_ids, history):
    schema = deepcopy(schema)
    props, defs = schema["properties"], schema["$defs"]
    for key in ["summary_source_fact_ids", "education", "projects", "selected_skill_ids"]:
        if key not in schema["required"]:
            schema["required"].append(key)
    choices(props["summary_source_fact_ids"], [e["source_id"] for e in catalog], 1)
    choices(props["core_skills"], skills)
    choices(props["selected_skill_ids"], skill_ids)
    props["selected_skill_ids"]["maxItems"] = min(16, len(set(skill_ids)))

    def variants(field, definition, kind):
        entries = [e for e in catalog if e["type"] == kind]
        if not entries and (kind != "experience" or not history):
            props[field] = {"type": "array", "items": {"type": "object"}, "maxItems": 0}
            defs.pop(definition, None)
            return
        branches = []
        owner_indexes = (
            range(len(history)) if kind == "experience" else dict.fromkeys(e["owner_index"] for e in entries)
        )
        for owner_index in owner_indexes:
            owned = [e for e in entries if e["owner_index"] == owner_index]
            row = deepcopy(defs[definition])
            row["additionalProperties"] = False
            if kind == "experience":
                identity = history[owner_index]
                row["properties"]["company"]["enum"] = [identity["company"]]
                row["properties"]["title"]["enum"] = [identity["title"]]
                bullet = deepcopy(defs["ResumeBullet"])
                choices(bullet["properties"]["source_fact_ids"], [e["source_id"] for e in owned], 1)
                row["properties"]["bullets"]["items"] = bullet
                if not owned:
                    row["properties"]["bullets"]["maxItems"] = 0
            else:
                choices(row["properties"]["source_fact_ids"], [e["source_id"] for e in owned], 1)
                if "source_fact_ids" not in row["required"]:
                    row["required"].append("source_fact_ids")
                key = "name" if kind == "project" else "institution"
                row["properties"][key]["enum"] = [owned[0]["owner"]]
                if kind == "project":
                    choices(row["properties"]["technologies"], skills)
            branches.append(row)
        props[field]["items"] = branches[0] if len(branches) == 1 else {"anyOf": branches}
        if kind in {"experience", "education"}:
            props[field]["minItems"] = len(branches)
            props[field]["maxItems"] = len(branches)
        else:
            props[field]["minItems"] = 1
        defs.pop(definition, None)

    variants("experience", "ResumeExperience", "experience")
    variants("education", "ResumeEducation", "education")
    variants("projects", "ResumeProject", "project")
    # ResumeBullet is inlined with per-employer IDs above.
    defs.pop("ResumeBullet", None)
    return schema


def validate_resume_selections(resume, catalog, history):
    """Independent ownership/coverage boundary; array length alone is insufficient."""
    required = {"summary_source_fact_ids", "education", "projects", "selected_skill_ids"}
    if not required <= resume.model_fields_set:
        raise ValueError("Missing required CV selections or citations")
    lookup = {e["source_id"]: e for e in catalog}
    if catalog and (not resume.summary_source_fact_ids or any(i not in lookup for i in resume.summary_source_fact_ids)):
        raise ValueError("Invalid summary citations")
    expected = [(row["company"], row["title"]) for row in history]
    actual = [(row.company, row.title) for row in resume.experience]
    from collections import Counter

    if Counter(expected) != Counter(actual):
        raise ValueError("Every employment must be present exactly once")
    for row in resume.experience:
        owners = {i for i, e in enumerate(history) if (e["company"], e["title"]) == (row.company, row.title)}
        for bullet in row.bullets:
            if any(
                i not in lookup or lookup[i]["type"] != "experience" or lookup[i]["owner_index"] not in owners
                for i in bullet.source_fact_ids
            ):
                raise ValueError("Bullet citations belong to another employment")
    expected_education = {e["owner_index"] for e in catalog if e["type"] == "education"}
    actual_education = []
    for row in resume.education:
        citations = [lookup.get(i) for i in row.source_fact_ids]
        if not citations or any(
            e is None or e["type"] != "education" or e["owner"] != row.institution for e in citations
        ):
            raise ValueError("Invalid education citations")
        owners = {e["owner_index"] for e in citations}
        if len(owners) != 1:
            raise ValueError("Education citations mix institutions")
        actual_education.extend(owners)
    if set(actual_education) != expected_education or len(actual_education) != len(expected_education):
        raise ValueError("Every education entry must be present exactly once")
    project_owners = []
    for row in resume.projects:
        citations = [lookup.get(i) for i in row.source_fact_ids]
        if not citations or any(e is None or e["type"] != "project" or e["owner"] != row.name for e in citations):
            raise ValueError("Invalid project citations")
        owners = {e["owner_index"] for e in citations}
        if len(owners) != 1 or project_owners and owners & set(project_owners):
            raise ValueError("Duplicate or mixed project identity")
        project_owners.extend(owners)
