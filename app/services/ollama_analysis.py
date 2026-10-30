"""Compact, reference-based Ollama analysis; expand facts/quotes only in code.

Budgets here are planning estimates, never reported as measured token counts.
Every source passage survives batching and must receive an explicit disposition.
"""

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.interpretation import JobInterpretation, ModelComponent, ModelRequirement
from app.models.job import RequirementPriority, RequirementStatus
from app.services.ai_provider import AIProviderError
from app.services.evidence_matching import EvidenceMatcher
from app.services.fact_catalog import FactCatalog
from app.services.job_sections import clean_source_line, extract_sections


class OllamaAnalysisError(AIProviderError):
    def __init__(self, kind, message, *, recovered=None):
        super().__init__(message)
        self.kind = kind
        self.recovered = recovered or []


class CompactComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: str = Field(min_length=1, max_length=120)
    s: RequirementStatus
    f: list[str] = Field(default_factory=list, max_length=32)
    why: str = Field(default="", max_length=280)
    lvl: str = Field(default="", max_length=40)


class CompactAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p: str
    k: Literal["requirement", "competency", "responsibility", "context"]
    n: str = Field(default="", max_length=120)
    priority: RequirementPriority = RequirementPriority.PREFERRED
    s: RequirementStatus = RequirementStatus.MISSING
    f: list[str] = Field(default_factory=list, max_length=64)
    why: str = Field(default="", max_length=280)
    op: Literal["single", "all", "any", "ambiguous"] = "single"
    c: list[CompactComponent] = Field(default_factory=list, max_length=64)
    lvl: str = Field(default="", max_length=40)
    yrs: float | None = Field(default=None, ge=0, le=100)
    uncertain: bool = False


class CompactInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[CompactAssessment]

    @model_validator(mode="before")
    @classmethod
    def expand_keyed_recovery(cls, value):
        if isinstance(value, dict) and set(value) == {"assessments"}:
            assessments = value["assessments"]
            if not isinstance(assessments, dict) or any(not isinstance(row, dict) or "p" in row for row in assessments.values()):
                raise ValueError("Keyed recovery requires assessment objects without repeated passage IDs")
            return {"rows": [dict(row, p=pid) for pid, row in assessments.items()]}
        return value


COMPACT_PROMPT = """Interpret every supplied job passage using only the indexed candidate evidence.
Evidence maps F IDs to [kind, owner ID, full fact, documented strength].
Owner rows use evidence_owner_fields; strength codes resolve through evidence_strengths. Owner IDs resolve through evidence_owners; employment_dates provide dated roles.
Return {"assessments": {PASSAGE_ID: assessment}}. Every passage ID is a required key exactly once. Omit p inside assessment values. Use short references. p=passage ID, k=requirement/competency/responsibility/context,
n=concise English capability label, s=strong/partial/missing/absent, f=evidence IDs,
why=one concise explanation of scope and evidence, op=single/all/any/ambiguous,
c=components (n,s,f; optional why only for a specific nuance; optional lvl),
lvl=required proficiency, yrs=minimum relevant years. Omit routine component reasons:
code displays the evidence/status explanation. Do not repeat "not confirmed" for every component.
Cover EVERY passage. The requires_assessment flag marks a candidate condition,
including conditions under unfamiliar headings: it MUST be a requirement or competency,
not context/responsibility. For headings, company, benefits and recruitment use context.
For duties use responsibility; a duty is not a prior-experience qualification.
Portal/role technology tags are checked independently by code. Use context with
only p and k for those tag passages; do not generate a long component list for them.
Never infer mandatory priority from portal tags.
Soft skill descriptions are candidate capabilities, not company context: classify them
as competencies unless a qualification priority is explicit. Tenure, language proficiency
and hands-on experience conditions remain qualifications even under unfamiliar headings.
For context/responsibility return ONLY p and k; their original text is kept by code.
For requirements/competencies supply n, priority, s, f, why; include optional fields
only when needed. Return one row per capability, use components for AND/OR conditions.
Never repeat source quotes, full evidence facts or long descriptions in the response.
job_source preserves the complete offer across batches; classify only the supplied passage IDs.
Hints and section labels are advisory, never authoritative. Classify each passage by
its meaning in the complete source, regardless of heading wording, formatting or order.
An inherited duty/benefit hint cannot override an explicit candidate qualification.
Preserve every heading and non-qualification passage as context; never score a heading.
Keep required scope, tenure, levels, negations and preferably optional qualifiers intact.
Never cite broad Microsoft 365 or Active Directory use as evidence of Exchange Online, Entra ID or Intune practice. For minimum tenure, cite the actual support duties of dated employment, not unrelated technologies. Use one compound label per passage, preserving every condition in components. A clause introduced by najlepiej/preferably is optional and must not weaken the main minimum. AND requires each component. OR/examples require an applicable alternative, not all examples.
A technology/file name or a workflow existing in a repository does not prove successful
execution, advanced competence or commercial experience. Cite evidence at its actual scope:
declaration, documented use, implemented artifact, or confirmed operational result.
B2/daily English does not establish fluency. Missing evidence is missing, not absent;
absent requires explicit negative evidence. No records or no listed certification MUST be missing, NEVER absent. Titles/employers and job text are not candidate facts.
Do not invent IDs, omit qualifications, assess the same capability twice, or add facts.
All generated explanations must be English; original source text remains unchanged."""


@dataclass
class AnalysisInventory:
    passages: dict
    evidence: dict
    owners: list
    matcher: object = None
    source_text: str = ""

    @classmethod
    def build(cls, job, profile, bank=None):
        units, _ = extract_sections(job.job_description)
        passages = {}
        # Include unrecognized headings and all administrative/duty text, too.
        # A parser hint cannot silently remove a passage from model interpretation.
        for position, text in enumerate([job.role, *job.job_description.splitlines()]):
            text = text.strip()
            if not text:
                continue
            cleaned = clean_source_line(text)
            related = [u for u in units if u.quote.strip() in {text, cleaned}] if position else []
            metadata = related or [u for u in units if cleaned in u.supporting_quotes]
            hints = sorted({u.category for u in metadata})
            section = metadata[0].section if metadata else ""
            passages[f"P{len(passages) + 1}"] = {
                "text": related[0].quote if related else text,
                "hints": hints,
                "section": section,
                "context_only": position == 0,
            }
        matcher = EvidenceMatcher(FactCatalog(profile), bank)
        entries = matcher.entries
        evidence = {f"F{i + 1}": e for i, e in enumerate(entries)}
        # Dates are separate, once per owner: evidence references establish duties;
        # job titles alone never prove competence or counted tenure.
        owners = [
            {"index": i, "company": e.company, "title": e.title, "start": e.start, "end": e.end}
            for i, e in enumerate(profile.experience)
        ]
        return cls(passages, evidence, owners, matcher, job.job_description)

    def payload(self, ids):
        from app.services.evidence_strength import evidence_strength

        owners, owner_ids, evidence = {}, {}, {}
        for fid, entry in self.evidence.items():
            key = (entry.kind, entry.owner_index, entry.owner_name)
            if key not in owner_ids:
                oid = f"O{len(owners) + 1}"
                owner_ids[key] = oid
                owners[oid] = {
                    "name": entry.owner_name,
                    "employment_index": entry.owner_index if entry.kind == "experience" else None,
                }
            evidence[fid] = [entry.kind, owner_ids[key], entry.text, evidence_strength(entry)]
        from app.services.ollama_payload import compact_analysis

        return compact_analysis({
            "stage": "analyze_job",
            "job_source": self.source_text,
            "passages": [
                {"id": i, **self.passages[i], "requires_assessment": needs_assessment(self.passages[i])} for i in ids
            ],
            "evidence": evidence,
            "evidence_owners": owners,
            "employment_dates": self.owners,
        })

    def schema(self, ids):
        schema = CompactInterpretation.model_json_schema()
        if not ids:
            schema["properties"]["rows"] = {"type": "array", "items": {"type": "object"}, "maxItems": 0}
            return schema
        # Bound every generated array and use short ID enums. This avoids repeating
        # long IDs, quoted job text and fact text in every generated component.
        schema["properties"]["rows"]["minItems"] = len(ids)
        schema["properties"]["rows"]["maxItems"] = max(1, len(ids) * 3)
        schema["$defs"]["CompactAssessment"]["properties"]["p"]["enum"] = ids
        if self.evidence:
            schema["$defs"]["EvidenceId"] = {"type": "string", "enum": list(self.evidence)}
            for kind in ["CompactAssessment", "CompactComponent"]:
                schema["$defs"][kind]["properties"]["f"]["items"] = {"$ref": "#/$defs/EvidenceId"}
        else:
            for kind in ["CompactAssessment", "CompactComponent"]:
                schema["$defs"][kind]["properties"]["f"]["maxItems"] = 0
        # Use disjoint ID enums, rather than unsupported custom options or prose
        # retries: a known qualification cannot choose a context-only row type.
        from copy import deepcopy

        groups = {"QualificationRow": [], "CapabilityRow": [], "OtherRow": []}
        for pid in ids:
            if objective_condition(self.passages[pid]):
                groups["QualificationRow"].append(pid)
            elif needs_assessment(self.passages[pid]):
                groups["CapabilityRow"].append(pid)
            else:
                groups["OtherRow"].append(pid)
        if not groups["OtherRow"]:
            # Targeted recovery needs a flat grammar: every remaining passage
            # is an assessable capability. Mixed union branches otherwise let
            # some local runtimes repeat context-only dispositions.
            row_schema = deepcopy(schema["$defs"]["CompactAssessment"])
            row_schema["properties"]["k"]["enum"] = ["requirement", "competency"]
            row_schema["required"] = list(dict.fromkeys(row_schema["required"] + ["n", "s", "f", "why", "priority"]))
            row_schema["properties"]["n"]["minLength"] = 1
            row_schema["properties"]["why"]["minLength"] = 1
            schema["$defs"]["AssessmentRow"] = row_schema
            schema["properties"]["rows"]["items"] = {"$ref": "#/$defs/AssessmentRow"}
            del schema["$defs"]["CompactAssessment"]
            return schema
        variants = []
        for name, pids in groups.items():
            if not pids:
                continue
            row_schema = deepcopy(schema["$defs"]["CompactAssessment"])
            row_schema["properties"]["p"]["enum"] = pids
            if name != "OtherRow":
                row_schema["properties"]["k"]["enum"] = (
                    ["requirement"] if name == "QualificationRow" else ["requirement", "competency"]
                )
                # A real assessed row always needs a name, explanation and status.
                row_schema["required"] = list(
                    dict.fromkeys(row_schema["required"] + ["n", "s", "f", "why", "priority"])
                )
                row_schema["properties"]["n"]["minLength"] = 1
                row_schema["properties"]["why"]["minLength"] = 1
            else:
                row_schema["anyOf"] = [
                    {"properties": {"k": {"enum": ["context", "responsibility"]}, "n": {"enum": [""]}, "why": {"enum": [""]}, "f": {"maxItems": 0}, "c": {"maxItems": 0}}},
                    {"properties": {"k": {"enum": ["requirement", "competency"]}, "n": {"minLength": 1}, "why": {"minLength": 1}}, "required": ["n", "why", "s", "f", "priority"]},
                ]
            schema["$defs"][name] = row_schema
            variants.append({"$ref": f"#/$defs/{name}"})
        schema["properties"]["rows"]["items"] = variants[0] if len(variants) == 1 else {"anyOf": variants}
        del schema["$defs"]["CompactAssessment"]
        return schema

    def keyed_schema(self, ids):
        """Each passage is required exactly once; context cannot claim a skill."""
        from copy import deepcopy

        definitions = CompactInterpretation.model_json_schema()["$defs"]
        base = definitions.pop("CompactAssessment")
        properties = {}
        for pid in ids:
            passage = self.passages[pid]
            assessable = needs_assessment(passage)
            qualification = objective_condition(passage)
            fixed_context = passage["context_only"] and not assessable
            kind = "Qualification" if qualification else "Assessment" if assessable else "Context" if fixed_context else "Open"
            if kind not in definitions:
                row = deepcopy(base)
                row["properties"].pop("p")
                row["required"] = ["k"]
                if kind == "Context":
                    row["properties"] = {"k": {"type": "string", "enum": ["context"]}}
                else:
                    row["properties"]["k"]["enum"] = ["requirement"] if qualification else ["requirement", "competency"] if assessable else ["requirement", "competency", "context", "responsibility"]
                    if kind != "Open":
                        row["required"] += ["n", "s", "f", "why", "priority"]
                    row["properties"]["n"]["minLength"] = 1
                    row["properties"]["why"]["minLength"] = 1
                    if kind == "Open":
                        row["properties"]["n"]["minLength"] = 0
                        row["properties"]["why"]["minLength"] = 0
                        row["anyOf"] = [
                            {"properties": {"k": {"enum": ["context", "responsibility"]}}},
                            {"properties": {"k": {"enum": ["requirement", "competency"]}, "n": {"minLength": 1}, "why": {"minLength": 1}},
                             "required": ["n", "s", "f", "why", "priority"]},
                        ]
                    for target in [row, definitions["CompactComponent"]]:
                        refs = target["properties"]["f"]
                        if self.evidence:
                            refs["items"] = {"type": "string", "enum": list(self.evidence)}
                        else:
                            refs["maxItems"] = 0
                definitions[kind] = row
            # Bind named product scopes to independently checked source evidence.
            # Every evidence record still travels in the payload; this only bounds
            # which IDs can prove this particular product at its requested scope.
            if assessable and self.matcher:
                import re

                from app.services.semantic_requirements import source_components
                parts, operator = source_components(passage["text"])
                scopes = parts or [passage["text"]]
                named = all(re.search(r"Exchange Online|Entra ID|Intune|Defender for Endpoint|macOS", value, re.I) for value in scopes)
                # Strip grammatical qualifiers for matching a single named product,
                # retaining practical scope in the independent matcher query.
                checks = []
                for value in scopes:
                    found = re.findall(r"Exchange Online|Entra ID|Intune|Defender for Endpoint|macOS", value, re.I)
                    if len(found) != 1:
                        break
                    query = ("Practical knowledge of " if re.search(r"praktyczn|practical|experience|hands.on", value, re.I) else "Knowledge of ") + found[0]
                    checks.append(self.matcher.match(query))
                if named and len(checks) == len(scopes) and all(check and check.status == RequirementStatus.MISSING for check in checks):
                    kind = f"MissingProduct_{pid}"
                    row = deepcopy(definitions["Qualification" if qualification else "Assessment"])
                    row["properties"]["s"] = {"type": "string", "enum": ["missing"]}
                    row["properties"]["f"] = {"type": "array", "items": {"type": "string"}, "maxItems": 0}
                    component = deepcopy(definitions["CompactComponent"])
                    component["properties"]["s"] = {"type": "string", "enum": ["missing"]}
                    component["properties"]["f"] = {"type": "array", "items": {"type": "string"}, "maxItems": 0}
                    row["properties"]["c"]["items"] = component
                    if parts:
                        row["properties"]["op"]["enum"] = [operator]
                    definitions[kind] = row
            properties[pid] = {"$ref": f"#/$defs/{kind}"}
        return {"type": "object", "$defs": definitions,
                "properties": {"assessments": {"type": "object", "properties": properties, "required": ids, "additionalProperties": False}},
                "required": ["assessments"], "additionalProperties": False}

    def validate_rows(self, rows, ids):
        allowed = set(ids)
        if len(rows) > len(ids) * 3:
            raise OllamaAnalysisError("schema", "Ollama exceeded the bounded assessment row count.")
        seen, valid = {}, []
        for row in rows:
            if row.p not in allowed:
                raise OllamaAnalysisError("coverage", "Ollama referenced an unknown job passage.")
            # An explicit minimum tenure / required language condition cannot
            # become an unweighted role tag. Correct category only; retain model
            # evidence/status for the independent factual/proficiency validator.
            if row.k == "competency" and objective_condition(self.passages[row.p]):
                row = row.model_copy(deep=True)
                row.k = "requirement"
                hints = self.passages[row.p]["hints"]
                from app.services.job_sections import PREFERENCE_MARKER

                optional = set(hints) & {"preferred", "nice_to_have"} or PREFERENCE_MARKER.search(
                    self.passages[row.p]["text"]
                )
                row.priority = RequirementPriority.PREFERRED if optional else RequirementPriority.MANDATORY
            if row.k in {"requirement", "competency"} and (not row.n.strip() or not row.why.strip()):
                raise OllamaAnalysisError("schema", "Ollama omitted a capability label or evidence explanation.")
            refs = row.f + [i for c in row.c for i in c.f]
            if any(i not in self.evidence for i in refs):
                raise OllamaAnalysisError("schema", "Ollama referenced unknown candidate evidence.")
            key = (row.p, row.k, row.n.casefold().strip())
            if key in seen:
                if seen[key].s != row.s:
                    raise OllamaAnalysisError(
                        "coverage", "Ollama returned conflicting duplicate assessments; review required."
                    )
                continue
            seen[key] = row
            valid.append(row)
        return valid

    def expand(self, rows):
        requirements, competencies, responsibilities, context = [], [], [], []
        merged = {}
        for row in rows:
            text = self.passages[row.p]["text"]
            if row.k in {"responsibility", "context"}:
                target = responsibilities if row.k == "responsibility" else context
                target.append({"source_quote": text, "text": text})
                continue
            item = ModelRequirement(
                name=row.n,
                source_quote=text,
                priority=row.priority,
                status=row.s,
                source_fact_ids=[self.evidence[i].source_id for i in row.f],
                reason=row.why,
                operator=row.op,
                required_level=row.lvl,
                required_years=row.yrs,
                components=[
                    ModelComponent(
                        name=c.n,
                        status=c.s,
                        source_fact_ids=[self.evidence[i].source_id for i in c.f],
                        reason=c.why
                        or {
                            "strong": "Cited facts confirm this component at the stated scope.",
                            "partial": "Evidence supports part of this component; scope/level needs review.",
                            "missing": "Not confirmed in the supplied profile; this is not proof of inability.",
                            "absent": "Explicit negative evidence must support this gap.",
                        }[c.s.value],
                        required_level=c.lvl,
                    )
                    for c in row.c
                ],
                classification_basis=f"Model interpretation of indexed source passage {row.p}",
                interpretation_uncertain=row.uncertain,
            )
            key = (
                row.k,
                text,
                item.name.casefold().strip(),
                item.priority,
                item.operator,
                item.required_level,
                item.required_years,
            )
            if key in merged:
                previous = merged[key]
                if previous.status != item.status:
                    raise OllamaAnalysisError(
                        "coverage", "Ollama returned conflicting duplicate assessments; review required."
                    )
                previous.source_fact_ids = list(dict.fromkeys(previous.source_fact_ids + item.source_fact_ids))
                continue
            merged[key] = item
            (requirements if row.k == "requirement" else competencies).append(item)
        return JobInterpretation(
            requirements=requirements,
            role_competencies=competencies,
            responsibilities=responsibilities,
            source_context=context,
        )


def estimate_tokens(value):
    """Conservative UTF-8 size heuristic, not a tokenizer or an API measurement."""
    return (len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()) + 1) // 2


def plan_batches(inventory, output_limit, context_limit, prompt_tokens=None):
    batches, current, cost = [], [], 0
    def context_cost(ids):
        if prompt_tokens is not None:
            return prompt_tokens(inventory.payload(ids)) + 512 + output_limit
        # Safe offline fallback; format grammar is not input context.
        return estimate_tokens(inventory.payload(ids)) + 1536 + output_limit
    # Keep existing deployment limits. Separate generated-output planning from
    # prompt/context reservations; batching is the escape hatch, not a bigger GPU.
    for pid, passage in inventory.passages.items():
        qualification = needs_assessment(passage)
        row_cost = 160 + min(1200, len(passage["text"]) // 6) if qualification else 100 if not passage["context_only"] else 8
        proposed = current + [pid]
        fits_output = cost + row_cost <= int(output_limit * 0.75)
        fits_context = context_cost(proposed) <= context_limit
        if current and (not fits_output or not fits_context):
            batches.append(current)
            current, cost = [], 0
            proposed = [pid]
        if context_cost(proposed) > context_limit:
            raise OllamaAnalysisError(
                "context_budget",
                "Candidate evidence and a source passage exceed the configured context budget; analysis requires review.",
            )
        current, cost = proposed, cost + row_cost
    if current:
        batches.append(current)
    return batches


def closed_rows(content):
    """Salvage only complete, valid array or keyed rows from truncated JSON."""
    import re

    array = re.match(r'\s*\{\s*"rows"\s*:\s*\[', content)
    keyed = re.match(r'\s*\{\s*"assessments"\s*:\s*\{', content)
    match = array or keyed
    if not match:
        return []
    decoder, position, rows = json.JSONDecoder(), match.end(), []
    while position < len(content):
        while position < len(content) and content[position] in " \t\r\n,":
            position += 1
        try:
            value, position = decoder.raw_decode(content, position)
            if keyed:
                if not isinstance(value, str):
                    break
                pid = value
                while position < len(content) and content[position].isspace():
                    position += 1
                if position == len(content) or content[position] != ':':
                    break
                position += 1
                while position < len(content) and content[position].isspace():
                    position += 1
                value, position = decoder.raw_decode(content, position)
                if not isinstance(value, dict) or 'p' in value:
                    break
                value = dict(value, p=pid)
            rows.append(CompactAssessment.model_validate(value))
        except (ValueError, TypeError):
            break
    return rows


def needs_assessment(passage):
    """Detect candidate capability passages left as context, not infer their status."""
    import re

    if passage.get("assessment_required") or objective_condition(passage):
        return True
    text = clean_source_line(passage["text"])
    if text.endswith(":") or len(text.split()) < 2:
        return False
    return bool(
        re.match(
            r"^(?:\d+(?:\.\d+)?\+?\s*years?\b|experience\b|hands.on experience\b|knowledge\b|familiarity\b|proficiency\b|understanding\b|practical knowledge\b|(?:praktyczn\w*\s+)?znajomoś\w*\b|doświadczen\w*\b|umiejętnoś\w*\b|ability\b|able to\b|excellent\b|strong attention\b|problem.solving\b|open to learning\b|must\b|fluen\w*\b)",
            text,
            re.I,
        )
    )


def objective_condition(passage):
    import re

    text = clean_source_line(passage["text"])
    tenure = re.match(r"^(?:(?:at least|minimum|at minimum)\s+)?\d+(?:\.\d+)?\+?\s*years?\b.*\bexperience\b", text, re.I)
    language = re.match(r"^(?:experience|fluency|fluent|candidates? must|must|requires?)\b", text, re.I) and re.search(
        r"\bfluent\b|\bfluency\b|\b[ABC][12]\b", text, re.I
    )
    return bool(tenure or language)
