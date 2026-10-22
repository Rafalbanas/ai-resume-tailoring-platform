import json

import httpx
import pytest

from app.core.config import Settings
from app.models.candidate import CandidateProfile
from app.models.job import JobRequest, JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.diagnostics import DiagnosticLogStore
from app.services.evidence_matching import EvidenceMatcher
from app.services.fact_catalog import FactCatalog
from app.services.ollama_analysis import AnalysisInventory, OllamaAnalysisError, closed_rows, plan_batches
from app.services.ollama_provider import OllamaProvider


def offer(count):
    return JobRequest(
        company="Example",
        role="Engineer",
        job_description="Requirements\n" + "\n".join(f"Experience with Tool{i}." for i in range(count)),
    )


def body_rows(body):
    payload = json.loads(body["messages"][1]["content"])
    return [
        {
            "p": p["id"],
            "k": "requirement",
            "n": p["text"],
            "priority": ("preferred" if "preferred" in p["hints"] else "mandatory"),
            "s": "missing",
            "f": [],
            "why": "Not confirmed in the supplied profile.",
        }
        if set(p["hints"]) & {"mandatory", "preferred", "nice_to_have"}
        else {"p": p["id"], "k": "context"}
        for p in payload["passages"]
    ]


def make_provider(handler, **options):
    options.setdefault("ollama_draft_review_enabled", False)
    return OllamaProvider(Settings(_env_file=None, **options), transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [5, 22, 48])
async def test_adaptive_complete_analysis_counts_and_bounded_calls(count, profile):
    requests = []

    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps({"rows": body_rows(body)})}, "done": True, "done_reason": "stop"},
        )

    p = make_provider(handler)
    result = await p.analyze_job(offer(count), profile)
    assert result.is_reliable and len(result.requirements) == count
    assert result.requirement_counts["mandatory"] == count
    assert len(requests) == (1 if count <= 22 else 2)
    ids = [p["id"] for r in requests for p in json.loads(r["messages"][1]["content"])["passages"]]
    assert len(ids) == len(set(ids)) == count + 2
    assert all(r["options"] == {"temperature": 0, "num_predict": 8192, "num_ctx": 32768} for r in requests)
    assert all(r["think"] is False and r["stream"] is False for r in requests)
    assert all(len(json.dumps(r["format"])) < 12000 for r in requests)


@pytest.mark.asyncio
async def test_truncated_response_recovers_only_missing_passages(profile):
    requests = []

    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        rows = body_rows(body)
        if len(requests) == 1:
            content = '{"rows":[' + ",".join(json.dumps(r) for r in rows[:4]) + ',{"p":"P5","k":'
            return httpx.Response(
                200,
                json={
                    "message": {"content": content},
                    "done_reason": "length",
                    "eval_count": 8192,
                    "prompt_eval_count": 400,
                },
            )
        return httpx.Response(200, json={"message": {"content": json.dumps({"rows": rows})}, "done_reason": "stop"})

    p = make_provider(handler)
    result = await p.analyze_job(offer(5), profile)
    assert result.is_reliable and len(result.requirements) == 5
    assert len(requests) == 2
    pending = json.loads(requests[1]["messages"][1]["content"])["passages"]
    assert [x["id"] for x in pending] == ["P5", "P6", "P7"]
    assert p.call_metrics[0]["error_kind"] == "output_limit"
    assert p.call_metrics[1]["recovery_calls"] == 1
    assert requests[0]["options"] == requests[1]["options"]


@pytest.mark.asyncio
async def test_missing_coverage_is_never_accepted_and_retries_are_bounded(profile):
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"message": {"content": '{"rows":[]}'}, "done_reason": "stop"})

    p = make_provider(handler)
    with pytest.raises(OllamaAnalysisError) as exc:
        await p.analyze_job(offer(5), profile)
    assert exc.value.kind == "coverage" and len(calls) <= 5


def test_closed_rows_are_individually_validated_and_partial_objects_not_repaired():
    assert len(closed_rows('{"rows":[{"p":"P1","k":"context"},{"p":')) == 1
    assert closed_rows('{"rows":[{"p":"P1","k":"bogus"},') == []
    assert closed_rows('{"rows":[') == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "kind"), [("not JSON", "invalid_json"), ('{"rows":[{"p":"P1","k":"invalid"}]}', "schema")]
)
async def test_error_categories_distinguish_json_and_schema(content, kind, profile):
    async def handler(request):
        return httpx.Response(200, json={"message": {"content": content}, "done_reason": "stop"})

    p = make_provider(handler)
    with pytest.raises(OllamaAnalysisError) as exc:
        await p.analyze_job(offer(5), profile)
    assert exc.value.kind == kind and p.call_metrics[-1]["error_kind"] == kind


def test_context_budget_does_not_silently_drop_candidate_facts_or_source(profile):
    profile.summary_facts = ["Detailed source evidence. " * 2000]
    inventory = AnalysisInventory.build(offer(5), profile)
    with pytest.raises(OllamaAnalysisError) as exc:
        plan_batches(inventory, 8192, 16384)
    assert exc.value.kind == "context_budget"


def test_duties_context_unknown_headings_and_duplicate_source_are_retained(profile):
    job = JobRequest(
        company="Example",
        role="Engineer",
        job_description="Responsibilities\n"
        + ("Investigate long operational incidents. " * 200)
        + "\nRequirements\nPython\nPython\nUnusual qualification context\nMust understand protocol boundaries.",
    )
    inv = AnalysisInventory.build(job, profile)
    text = "\n".join(p["text"] for p in inv.passages.values())
    assert "Investigate long operational incidents." in text
    assert "Must understand protocol boundaries." in text
    batches = plan_batches(inv, 8192, 32768)
    assert {i for batch in batches for i in batch} == set(inv.passages)


def test_workflow_artifact_and_declaration_do_not_prove_pipeline_execution():
    p = CandidateProfile.model_validate(
        {
            "personal": {"name": "Example"},
            "skills": {"tools": ["GitHub Actions"]},
            "projects": [
                {
                    "name": "App",
                    "facts": ["The repository contains .github/workflows/ci.yml, a GitHub Actions workflow file."],
                }
            ],
        }
    )
    matcher = EvidenceMatcher(FactCatalog(p))
    result = matcher.match("GitHub Actions CI/CD pipeline")
    assert result.status == "partial"
    sources = matcher.sources([e.source_id for e in result.entries])
    assert {s["strength"] for s in sources} == {"declaration", "implementation"}
    from tests.test_provider_fallback import sample_workflow_response

    a = sample_workflow_response("mock", "test").analysis
    a.requirements = [
        JobRequirement(
            name="GitHub Actions CI/CD",
            source_quote="GitHub Actions CI/CD",
            priority="mandatory",
            status="strong",
            source_fact_ids=[e.source_id for e in matcher.entries],
            reason="Workflow exists.",
        )
    ]
    checked = AnalysisValidator(p).validate(a, "Requirements\nGitHub Actions CI/CD", semantic=True)
    assert checked.requirements[0].status == "partial"
    role = AnalysisValidator(p).validate(a, "TECH STACK\nGitHub Actions CI/CD", semantic=True)
    assert role.role_competency_counts["strong"] == 0
    assert role.role_competency_counts["partial"] == len(role.role_competencies)
    assert "0 confirmed competencies" in role.role_alignment_summary


def test_explicit_documented_pipeline_execution_is_not_arbitrarily_downgraded():
    p = CandidateProfile.model_validate(
        {
            "personal": {"name": "Example"},
            "projects": [
                {"name": "App", "facts": ["GitHub Actions CI pipeline runs tests and lint checks successfully."]}
            ],
        }
    )
    result = EvidenceMatcher(FactCatalog(p)).match("GitHub Actions CI/CD pipeline")
    assert result.status == "strong"


def test_diagnostic_metrics_are_allowlisted_and_unknown_counts_remain_unknown(tmp_path):
    store = DiagnosticLogStore(tmp_path)
    store.record(
        company="Example",
        role="Engineer",
        requested_provider="ollama",
        provider_used="ollama",
        model_used="test",
        fallback_occurred=False,
        assessed_requirements=22,
        call_metrics=[
            {
                "model": "test",
                "prompt_tokens": None,
                "completion_tokens": 8192,
                "error_kind": "output_limit",
                "raw_response": "PRIVATE FULL CV",
                "payload": {"api_key": "secret"},
            }
        ],
    )
    text = store.file_path.read_text()
    assert "PRIVATE" not in text and "api_key" not in text
    run = store.list_runs()[0]
    assert run["llm_call_count"] == 1 and run["output_limit_count"] == 1 and run["assessed_requirements"] == 22
    assert run["call_metrics"][0]["prompt_tokens"] is None


@pytest.mark.asyncio
async def test_unfamiliar_experience_heading_recovers_tenure_and_language_without_repeating_valid_rows(profile):
    job = JobRequest(
        company="Example",
        role="Engineer",
        job_description="Requirements\nPython\nExperience:\n1+ years of experience in DevOps.\nExperience in working with fluent English.",
    )
    bodies = []

    async def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        rows = body_rows(body)
        if len(bodies) > 1:
            for row in rows:
                row.update(
                    k="requirement",
                    n="Required experience" if row["p"] == "P5" else "Fluent English",
                    priority="mandatory",
                    s="missing",
                    f=[],
                    why="Required scope is not confirmed.",
                )
        return httpx.Response(200, json={"message": {"content": json.dumps({"rows": rows})}, "done_reason": "stop"})

    result = await make_provider(handler).analyze_job(job, profile)
    assert len(bodies) == 2 and result.is_reliable
    assert all(p["id"] in {"P5", "P6"} for p in json.loads(bodies[1]["messages"][1]["content"])["passages"])
    assert any("1+ years" in r.source_quote for r in result.requirements)
    assert any("fluent English" in r.source_quote for r in result.requirements)


def test_source_ids_never_replace_role_or_short_tag_with_a_longer_requirement(profile):
    job = JobRequest(
        company="Example",
        role="Python Engineer",
        job_description="Requirements\nWorking Python knowledge.\nTECH STACK\nPython",
    )
    inv = AnalysisInventory.build(job, profile)
    assert inv.passages["P1"]["text"] == "Python Engineer"
    assert inv.passages["P1"]["hints"] == []
    assert inv.passages["P5"]["text"] == "Python"
    assert "Working Python knowledge." in [p["text"] for p in inv.passages.values()]


def test_model_soft_skills_under_unknown_heading_survive_role_evidence_validation(profile):
    from tests.test_provider_fallback import sample_workflow_response

    a = sample_workflow_response("mock", "test").analysis
    text = "Unusual skills section\nAbility to collaborate with customer teams."
    a.requirements = []
    a.role_competencies = [
        JobRequirement(
            name="Customer collaboration",
            source_quote=text.splitlines()[1],
            priority="unspecified",
            status="missing",
            reason="No documented evidence for this complete scope.",
        )
    ]
    result = AnalysisValidator(profile).validate(a, text, semantic=True)
    assert any(r.name == "Customer collaboration" for r in result.role_competencies)
    assert result.role_competency_counts["missing"] == 1
    assert "1 not confirmed" in result.role_alignment_summary


@pytest.mark.asyncio
async def test_and_or_components_are_merged_without_promoting_missing_and_conditions(profile):
    job = JobRequest(
        company="Example", role="Engineer", job_description="Requirements\nPython and Docker\nPython or Docker"
    )

    async def handler(request):
        rows = body_rows(json.loads(request.content))
        for row in rows:
            if row["k"] == "requirement":
                row.update(
                    s="strong",
                    f=["F2"],
                    op="all" if row["p"] == "P3" else "any",
                    c=[
                        {"n": "Python", "s": "strong", "f": ["F2"], "why": "Declared knowledge."},
                        {"n": "Docker", "s": "missing", "f": [], "why": "Not confirmed."},
                    ],
                )
        return httpx.Response(200, json={"message": {"content": json.dumps({"rows": rows})}, "done_reason": "stop"})

    result = await make_provider(handler).analyze_job(job, profile)
    assert len(result.requirements) == 2
    assert result.requirements[0].operator == "all" and result.requirements[0].status == "partial"
    assert result.requirements[1].operator == "any" and result.requirements[1].status == "strong"
    assert len(result.requirements[0].components) == 2


@pytest.mark.asyncio
async def test_identical_repeated_requirements_are_deduplicated_without_losing_source_coverage(profile):
    job = JobRequest(
        company="Example",
        role="Engineer",
        job_description="Requirements\nExperience with Tool0.\nExperience with Tool0.",
    )

    async def handler(request):
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps({"rows": body_rows(json.loads(request.content))})},
                "done_reason": "stop",
            },
        )

    result = await make_provider(handler).analyze_job(job, profile)
    assert len(result.requirements) == 1 and result.requirement_counts["mandatory"] == 1
    assert result.is_reliable


@pytest.mark.asyncio
async def test_context_exhaustion_differs_from_output_limit(profile):
    async def handler(request):
        return httpx.Response(
            200,
            json={
                "message": {"content": '{"rows":['},
                "done_reason": "length",
                "prompt_eval_count": 32500,
                "eval_count": 200,
            },
        )

    p = make_provider(handler)
    with pytest.raises(OllamaAnalysisError) as exc:
        await p.analyze_job(offer(5), profile)
    assert exc.value.kind == "context_budget"
    assert p.call_metrics[0]["error_kind"] == "context_budget"


@pytest.mark.asyncio
async def test_timeout_unavailability_and_nonfinal_envelopes_are_distinct(profile):
    for kind in ["timeout", "unavailable", "incomplete_response", "envelope"]:

        async def handler(request, kind=kind):
            if kind == "timeout":
                raise httpx.ReadTimeout("timeout", request=request)
            if kind == "unavailable":
                raise httpx.ConnectError("offline", request=request)
            if kind == "envelope":
                return httpx.Response(200, json=["invalid envelope"])
            return httpx.Response(200, json={"message": {"content": "{}"}, "done": False})

        p = make_provider(handler)
        with pytest.raises(OllamaAnalysisError) as exc:
            await p.analyze_job(offer(5), profile)
        assert exc.value.kind == kind
        assert len(p.call_metrics) == 1 and p.call_metrics[0]["error_kind"] == kind


def test_schema_cannot_classify_qualifications_or_unfamiliar_tenure_as_context(profile):
    job = JobRequest(
        company="Example",
        role="Engineer",
        job_description="Requirements\nPython\nExperience:\n1+ years of experience in DevOps.",
    )
    inv = AnalysisInventory.build(job, profile)
    schema = inv.schema(list(inv.passages))
    assert schema["$defs"]["QualificationRow"]["properties"]["k"]["enum"] == ["requirement"]
    assert schema["$defs"]["CapabilityRow"]["properties"]["k"]["enum"] == ["requirement", "competency"]
    assert "P3" in schema["$defs"]["QualificationRow"]["properties"]["p"]["enum"]
    assert "P5" in schema["$defs"]["CapabilityRow"]["properties"]["p"]["enum"]
    assert "P3" not in schema["$defs"]["OtherRow"]["properties"]["p"]["enum"]
    assert "P5" not in schema["$defs"]["OtherRow"]["properties"]["p"]["enum"]


def test_targeted_recovery_uses_flat_schema_and_keeps_reference_ids(profile):
    inv = AnalysisInventory.build(offer(5), profile)
    ids = ["P3", "P4"]
    schema = inv.schema(ids)
    assert schema["properties"]["rows"]["items"] == {"$ref": "#/$defs/AssessmentRow"}
    row = schema["$defs"]["AssessmentRow"]
    assert row["properties"]["p"]["enum"] == ids
    assert row["properties"]["k"]["enum"] == ["requirement", "competency"]
    assert "why" in row["required"] and row["properties"]["why"]["minLength"] == 1


def test_minimum_tenure_and_fluency_cannot_become_unweighted_tags(profile):
    from app.services.ollama_analysis import CompactAssessment

    job = JobRequest(
        company="Example",
        role="Engineer",
        job_description="Experience:\n1+ years of experience in a related role.\nExperience with customers (fluent English)",
    )
    inv = AnalysisInventory.build(job, profile)
    rows = [
        CompactAssessment(
            p="P3", k="competency", n="Related experience", s="missing", why="Minimum tenure needs review."
        ),
        CompactAssessment(
            p="P4", k="competency", n="Customer English", s="missing", why="Required language needs review."
        ),
    ]
    checked = inv.validate_rows(rows, ["P3", "P4"])
    assert all(r.k == "requirement" and r.priority == "mandatory" for r in checked)
    assert all(r.s == "missing" for r in checked)
    result = AnalysisValidator(profile).validate(
        inv.expand(checked).to_analysis(job), job.job_description, semantic=True
    )
    assert result.requirement_counts["mandatory"] == 2
    assert all(r.status != "strong" for r in result.requirements)


def test_alias_duplicate_rows_merge_but_distinct_and_scopes_survive(profile):
    from app.services.semantic_requirements import merge_equivalent_source_rows

    quote = "Experience with virtualization technologies (VMware ESXi, KVM)."
    rows = [
        JobRequirement(
            name="Virtualization technologies (VMware ESXi, KVM)",
            source_quote=quote,
            status="partial",
            reason="Related evidence.",
        ),
        JobRequirement(name=quote, source_quote=quote, status="partial", reason="Related evidence."),
    ]
    merged = merge_equivalent_source_rows(rows)
    assert len(merged) == 1
    children = [
        JobRequirement(name="Python", source_quote="Python and Docker", status="strong"),
        JobRequirement(name="Docker", source_quote="Python and Docker", status="missing"),
    ]
    assert len(merge_equivalent_source_rows(children)) == 2
    combined = [
        JobRequirement(name="API integration", source_quote="API integration and API debugging"),
        JobRequirement(name="API debugging", source_quote="API integration and API debugging"),
    ]
    assert len(merge_equivalent_source_rows(combined)) == 2


def test_conflicting_duplicate_status_never_promotes_a_match():
    from app.services.semantic_requirements import merge_equivalent_source_rows

    rows = [
        JobRequirement(name="Python automation", source_quote="Python automation", status="strong"),
        JobRequirement(name="Python automation", source_quote="Python automation", status="partial"),
    ]
    merged = merge_equivalent_source_rows(rows)
    assert len(merged) == 1 and merged[0].status == "partial" and merged[0].interpretation_uncertain


def test_conflicting_duplicate_in_one_passage_triggers_fallback(profile):
    from app.services.ollama_analysis import CompactAssessment

    inventory = AnalysisInventory.build(offer(1), profile)
    rows = [CompactAssessment(p='P3', k='requirement', n='Tool0', s=status,
                              why='Evidence scope requires review.')
            for status in ('strong', 'missing')]
    with pytest.raises(OllamaAnalysisError, match='conflicting duplicate'):
        inventory.validate_rows(rows, ['P3'])


def test_conflicting_duplicate_source_passages_trigger_fallback(profile):
    from app.services.ollama_analysis import CompactAssessment

    job = JobRequest(company='Example', role='Support',
                     job_description='Requirements\nExperience with Python.\nExperience with Python.')
    inventory = AnalysisInventory.build(job, profile)
    rows = [CompactAssessment(p=pid, k='requirement', n='Python experience', s=status,
                              why='Evidence scope requires review.')
            for pid, status in [('P3', 'strong'), ('P4', 'missing')]]
    with pytest.raises(OllamaAnalysisError, match='conflicting duplicate'):
        inventory.expand(inventory.validate_rows(rows, ['P3', 'P4']))


def test_technology_declaration_cannot_establish_practical_and_component_experience():
    from app.models.job import RequirementComponent
    from tests.test_provider_fallback import sample_workflow_response

    p = CandidateProfile.model_validate(
        {"personal": {"name": "Example"}, "skills": {"tools": ["Docker", "Kubernetes"]}}
    )
    refs = {e.text: e.source_id for e in FactCatalog(p).prompt_entries}
    a = sample_workflow_response("mock", "test").analysis
    a.requirements = [
        JobRequirement(
            name="Docker and Kubernetes experience",
            source_quote="Experience with Docker and Kubernetes",
            status="strong",
            source_fact_ids=list(refs.values()),
            reason="Names are present.",
            operator="all",
            components=[
                RequirementComponent(name=n, status="strong", source_fact_ids=[refs[n]], reason="Declared technology.")
                for n in refs
            ],
        )
    ]
    result = AnalysisValidator(p).validate(a, "Requirements\nExperience with Docker and Kubernetes", semantic=True)
    assert result.requirements[0].status == "partial"
    assert all(c.status == "partial" for c in result.requirements[0].components)
    assert EvidenceMatcher(FactCatalog(p)).match("Experience with Docker").status == "partial"
    assert EvidenceMatcher(FactCatalog(p)).match("Knowledge of Docker").status == "strong"


def test_literal_statement_aliases_do_not_duplicate_framework_or_debugging_requirements():
    from app.services.semantic_requirements import merge_equivalent_source_rows

    cases = [
        (
            "Application layer technologies (Spring Boot, Angular)",
            "Practical knowledge of one or more of these technologies (at least on a basic level): Spring Boot, Angular",
        ),
        (
            "Troubleshooting and debugging on basic networking (Wireshark)",
            "Able to troubleshoot and debug issues on basic networking, knowledge of Wireshark",
        ),
    ]
    for label, quote in cases:
        rows = [
            JobRequirement(name=label, source_quote=quote, status="partial", required_level="basic"),
            JobRequirement(name=quote, source_quote=quote, status="partial", required_level="basic"),
        ]
        assert len(merge_equivalent_source_rows(rows)) == 1


@pytest.mark.asyncio
async def test_ollama_gets_four_targeted_repairs_without_repeating_completed_rows(profile):
    requests = []
    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        rows = body_rows(body)
        if len(requests) <= 4:
            rows = [row for row in rows if row['p'] != 'P4']
        return httpx.Response(200, json={'message': {'content': json.dumps({'rows': rows})}, 'done_reason': 'stop'})
    provider = make_provider(handler)
    result = await provider.analyze_job(offer(3), profile)
    assert result.is_reliable and len(result.requirements) == 3
    assert len(requests) == 5
    assert provider.call_metrics[-1]['recovery_calls'] == 4
    for request in requests[1:]:
        assert [p['id'] for p in json.loads(request['messages'][1]['content'])['passages']] == ['P4']
        assert request['format']['properties']['assessments']['required'] == ['P4']


@pytest.mark.asyncio
async def test_exhaustion_retains_completed_assessments_for_targeted_fallback(profile):
    calls = []
    async def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        rows = [row for row in body_rows(body) if row['p'] != 'P4']
        return httpx.Response(200, json={'message': {'content': json.dumps({'rows': rows})}, 'done_reason': 'stop'})
    provider = make_provider(handler, ollama_analysis_recovery_calls=2)
    with pytest.raises(OllamaAnalysisError) as caught:
        await provider.analyze_job(offer(3), profile)
    assert len(calls) == 3
    assert caught.value.unassessed_source_passages == ['Experience with Tool1.']
    assert {r.source_quote for r in caught.value.partial_analysis.requirements} == {'Experience with Tool0.', 'Experience with Tool2.'}
    assert 'Tool1' in caught.value.recovery_job_text and 'Tool0' not in caught.value.recovery_job_text


@pytest.mark.asyncio
async def test_final_semantic_coverage_requests_targeted_ollama_repair(profile, monkeypatch):
    import app.services.ollama_provider as module
    requests = []
    original = module.AnalysisValidator.validate
    validations = []
    def validate(self, analysis, text, **kwargs):
        result = original(self, analysis, text, **kwargs)
        validations.append(result)
        if len(validations) == 1:
            result.is_reliable = False
            result.unassessed_source_passages = ['Experience with Tool1.']
        return result
    monkeypatch.setattr(module.AnalysisValidator, 'validate', validate)
    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={'message': {'content': json.dumps({'rows': body_rows(body)})}, 'done_reason': 'stop'})
    result = await make_provider(handler).analyze_job(offer(3), profile)
    assert result.is_reliable and len(requests) == 2
    assert [p['text'] for p in json.loads(requests[1]['messages'][1]['content'])['passages']] == ['Experience with Tool1.']


def test_validated_role_assessment_counts_as_source_coverage(profile):
    from app.models.job import JobAnalysis
    from app.services.ollama_analysis import CompactAssessment
    source = JobRequest(company='Example', role='Support',
        job_description='About the role\nUnderstanding unusual platform behaviour.')
    inventory = AnalysisInventory.build(source, profile)
    pid = next(pid for pid, item in inventory.passages.items() if item['text'].startswith('Understanding'))
    interpretation = inventory.expand([CompactAssessment(p=pid, k='competency',
        n='Understanding unusual platform behaviour', s='missing', why='Not confirmed by candidate evidence.')])
    result = AnalysisValidator(profile).validate(interpretation.to_analysis(source), source.job_description, semantic=True)
    assert result.is_reliable and result.role_competencies
    assert not result.unassessed_source_passages
    result.unassessed_source_passages = ['Understanding unusual platform behaviour.']
    # Persisted incomplete reports cannot become reliable just by revalidation.
    reopened = AnalysisValidator(profile).validate(JobAnalysis.model_validate_json(result.model_dump_json()),
                                                   source.job_description, semantic=True)
    assert not reopened.is_reliable and reopened.unassessed_source_passages


def test_truncated_keyed_rows_preserve_only_complete_valid_objects():
    valid = '"P3":{"k":"requirement","n":"XML","s":"missing","why":"No evidence."}'
    rows = closed_rows('{"assessments":{' + valid + ',"P4":{"k":')
    assert len(rows) == 1 and rows[0].p == 'P3'
    assert closed_rows('{"assessments":{"P3":{"p":"P9","k":"context"},') == []


@pytest.mark.asyncio
async def test_truncated_keyed_repair_keeps_completed_passages(profile):
    calls = []
    async def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        rows = body_rows(body)
        if len(calls) == 1:
            rows = [row for row in rows if row['p'] not in {'P4', 'P5'}]
        elif len(calls) == 2:
            completed = dict(rows[0])
            pid = completed.pop('p')
            content = '{"assessments":{' + json.dumps(pid) + ':' + json.dumps(completed) + ',"P5":{"k":'
            return httpx.Response(200, json={'message': {'content': content}, 'done_reason': 'length', 'eval_count': 8192})
        return httpx.Response(200, json={'message': {'content': json.dumps({'rows': rows})}, 'done_reason': 'stop'})
    result = await make_provider(handler).analyze_job(offer(3), profile)
    assert result.is_reliable and len(calls) == 3
    assert [p['id'] for p in json.loads(calls[2]['messages'][1]['content'])['passages']] == ['P5']
