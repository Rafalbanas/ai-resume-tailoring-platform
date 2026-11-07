"""Optional bounded LangGraph orchestration, no persistence or autonomous agents."""
import hashlib
from typing import Any, TypedDict

from app.services.ai_provider import ProviderResponseError, ProviderUnavailableError
from app.services.analysis_validator import AnalysisValidator
from app.services.ollama_analysis import AnalysisInventory, OllamaAnalysisError, plan_batches


class AnalysisState(TypedDict, total=False):
    inventory: Any
    candidate: Any
    validated: Any
    attempts: int
    feedback: list[str]
    error: bool


def graph_available():
    try:
        from langgraph.graph import StateGraph  # noqa: F401
        return True
    except ImportError:
        return False


async def analyze_with_graph(provider, job, profile):
    from langgraph.graph import END, START, StateGraph

    from app.services.hybrid_retrieval import prepare_inventory_retrieval
    from app.services.indexed_analysis import indexed_interpretation

    async def prepare_job(state):
        return {'inventory': AnalysisInventory.build(job, profile, provider.skills_bank),
                'attempts': 0, 'feedback': [], 'error': False}

    async def retrieve_candidate_evidence(state):
        semaphore = getattr(provider, 'semaphore', None)
        if semaphore is not None:
            async with semaphore:
                await prepare_inventory_retrieval(state['inventory'], provider.semantic_settings)
        else:
            await prepare_inventory_retrieval(state['inventory'], provider.semantic_settings)
        return {}

    async def extract_requirements(state):
        inventory = state['inventory']
        try:
            # Existing inventory validation checks F/P citations before expansion.
            # Batch planning remains bounded; each batch has no internal retries.
            batches = plan_batches(inventory, getattr(provider, 'analysis_output', 6144),
                                   getattr(provider, 'num_ctx', 32768))
            rows = []
            for ids in batches:
                from dataclasses import replace
                subset = replace(inventory, passages={pid: inventory.passages[pid] for pid in ids})
                if getattr(inventory, 'retrieval_hints', None):
                    subset.retrieval_hints = inventory.retrieval_hints
                interpretation = await indexed_interpretation(
                    provider, subset, validation_feedback=state['feedback'], max_attempts=1)
                # Retain provider-neutral requirements and dispositions without
                # asking another LLM to combine source passages.
                rows.append(interpretation)
            combined = rows[0]
            for extra in rows[1:]:
                for field in ('requirements', 'role_competencies', 'responsibilities', 'source_context'):
                    getattr(combined, field).extend(getattr(extra, field))
            return {'candidate': combined.to_analysis(job), 'attempts': state['attempts'] + 1,
                    'error': False}
        except (ProviderResponseError, ProviderUnavailableError, OllamaAnalysisError) as exc:
            if isinstance(exc, OllamaAnalysisError) and exc.kind not in {'schema', 'invalid_json', 'coverage'}:
                raise
            return {'attempts': state['attempts'] + 1, 'error': True,
                    'feedback': ['Recoverable provider response or source citation failure; reassess every supplied passage.']}

    async def validate_requirements(state):
        if state['error']:
            return {}
        validated = AnalysisValidator(profile, provider.skills_bank).validate(
            state['candidate'], f'{job.role}\n{job.job_description}', semantic=True)
        return {'validated': validated, 'feedback': list(dict.fromkeys(
            validated.completeness_issues + validated.classification_issues + validated.evidence_issues))}

    async def validate_evidence(state):
        # AnalysisValidator already invokes EvidenceMatcher, tenure, language and
        # scope ceilings. This node routes its result; it does not relax checks.
        return {}

    def route(state):
        if state['attempts'] < 2 and (state['error'] or not state['validated'].is_reliable):
            return 'extract_requirements'
        return 'finalize_analysis'

    async def finalize_analysis(state):
        if state['error']:
            raise ProviderResponseError('Graph analysis failed after one bounded retry; review required.')
        validated = state['validated']
        validated.company, validated.role = job.company, job.role
        validated.job_source = {'url': str(job.job_url or ''),
                                'sha256': hashlib.sha256(job.job_description.encode()).hexdigest()}
        validated._model_output = state['candidate'].model_dump(mode='json')
        # An unreliable result stays unreliable; no fabricated successful score.
        return {'validated': validated}

    graph = StateGraph(AnalysisState)
    for name, node in [('prepare_job', prepare_job), ('extract_requirements', extract_requirements),
                       ('validate_requirements', validate_requirements),
                       ('retrieve_candidate_evidence', retrieve_candidate_evidence),
                       ('validate_evidence', validate_evidence), ('finalize_analysis', finalize_analysis)]:
        graph.add_node(name, node)
    graph.add_edge(START, 'prepare_job')
    graph.add_edge('prepare_job', 'retrieve_candidate_evidence')
    graph.add_edge('retrieve_candidate_evidence', 'extract_requirements')
    graph.add_edge('extract_requirements', 'validate_requirements')
    graph.add_edge('validate_requirements', 'validate_evidence')
    graph.add_conditional_edges('validate_evidence', route,
                                ['extract_requirements', 'finalize_analysis'])
    graph.add_edge('finalize_analysis', END)
    # Never transmit candidate state to LangSmith even if host tracing is enabled.
    from langsmith import tracing_context
    with tracing_context(enabled=False):
        result = await graph.compile().ainvoke({}, {'recursion_limit': 16, 'callbacks': []})
    return result['validated']
