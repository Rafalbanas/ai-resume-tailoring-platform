"""Measured paired analysis benchmarks, not synthetic token estimates or CV exports."""
import asyncio
import copy
import hashlib
import json
import time
from collections import defaultdict

from app.models.benchmark import BenchmarkRequest
from app.models.job import JobRequest
from app.services.ai_provider import AIProviderError
from app.services.job_sections import clean_source_line, extract_sections
from app.services.offer_cleaning import clean_offer_text, normalize_offer_lines


def input_sizes(payload):
    # Character/byte counts explain composition; they are NOT token counts.
    return {key: {'characters': len(json.dumps(value, ensure_ascii=False, separators=(',', ':'))),
                  'bytes': len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())}
            for key, value in payload.items()}


def expected_qualifications(text):
    units, _ = extract_sections(normalize_offer_lines(text))
    return {clean_source_line(u.quote) for u in units if u.category in {'mandatory', 'preferred', 'nice_to_have'}}


async def run_benchmark(spec: BenchmarkRequest, state, on_stage, on_report=lambda report: None):
    started = time.perf_counter()
    profile = state.profile.model_copy(deep=True)
    bank = copy.deepcopy(getattr(state, 'skills_bank', None))
    base = state.providers['ollama']
    provider = await base.for_model(spec.ollama_model or base.model, spec.context)
    provider.analysis_recovery_calls = spec.recovery_calls
    provider.skills_bank = bank
    original_chat = provider._chat
    attempted = 0
    composition = []

    async def measured_chat(model, prompt, payload, **kwargs):
        nonlocal attempted
        if attempted >= spec.max_model_calls:
            raise AIProviderError('Benchmark model-call budget exhausted; no further model requests sent.')
        attempted += 1
        composition.append({'fields': input_sizes(payload), 'instruction_characters': len(prompt)})
        return await original_chat(model, prompt, payload, **kwargs)

    provider._chat = measured_chat
    report = {'version': 1, 'analysis_only': True, 'model': provider.model, 'context': spec.context,
              'profile_fingerprint': hashlib.sha256(profile.model_dump_json().encode()).hexdigest(),
              'skills_fingerprint': hashlib.sha256(json.dumps([skill.model_dump(mode='json') for skill in bank.skills], sort_keys=True).encode()).hexdigest() if bank else None,
              'recovery_limit_per_variant': spec.recovery_calls, 'max_model_calls': spec.max_model_calls,
              'case_timeout_seconds': spec.case_timeout_seconds, 'offers': [],
              'notes': ['Input composition is measured in characters/bytes, not estimated tokens.',
                        'Schema bytes are transport/grammar size, not a measured share of prompt tokens.',
                        'Token totals come only from provider reports and include failed/repair calls.',
                        'Account FIFO serializes these cases; unrelated model clients can still affect latency.',
                        'Original offers/profile are not modified; no CVs or application documents are created.']}
    for index, url in enumerate(spec.urls):
        on_stage(f'Benchmark {index + 1}/{len(spec.urls)}: extracting original offer')
        offer = {'url': str(url), 'variants': []}
        report['offers'].append(offer)
        try:
            extracted = await state.job_extractor.extract(str(url))
            if not extracted.company or not extracted.role or not extracted.job_description:
                raise ValueError('Offer extraction unavailable or unsafe; no model request sent for this offer.')
            job = JobRequest(company=extracted.company, role=extracted.role, job_url=str(url), job_description=extracted.job_description)
        except Exception as exc:
            offer.update(status='extraction_failed', error=str(exc)[:500])
            on_report(report)
            continue
        cleaned, cleaning = clean_offer_text(job.job_description)
        offer.update(company=job.company, role=job.role, cleaning=cleaning)
        expected = expected_qualifications(job.job_description)
        for variant, text in [('full', job.job_description), ('cleaned', cleaned)]:
            on_stage(f'Benchmark {index + 1}/{len(spec.urls)}: {variant} analysis ({job.company})')
            provider.call_metrics = []
            composition.clear()
            case_start = time.perf_counter()
            row = {'variant': variant, 'status': 'failed', 'is_reliable': False}
            offer['variants'].append(row)
            try:
                if hasattr(provider, 'analysis_output'):
                    from app.services.indexed_analysis import INDEXED_PROMPT
                    from app.services.ollama_analysis import AnalysisInventory, plan_batches
                    from app.services.ollama_provider import TRUTH_RULES
                    inventory = AnalysisInventory.build(job.model_copy(update={'job_description': text}), profile, bank)
                    counter = (lambda payload: provider.token_counter.prompt(f'{TRUTH_RULES}\n\n{INDEXED_PROMPT}', payload)) if provider.token_counter else None
                    row['planned_initial_batches'] = len(plan_batches(inventory, provider.analysis_output, provider.num_ctx, prompt_tokens=counter))
                async with asyncio.timeout(spec.case_timeout_seconds):
                    analysis = await provider.analyze_job(job.model_copy(update={'job_description': text}), profile)
                assessed = {clean_source_line(q) for req in analysis.requirements for q in [req.source_quote, *req.source_quotes]}
                missing = sorted(expected - assessed)
                row.update(status='ok' if analysis.is_reliable and not missing else 'review_required',
                           is_reliable=analysis.is_reliable, match_level=analysis.match_level.value,
                           expected_qualification_passages=len(expected), missing_original_qualifications=missing,
                           requirements=[{'name': r.name, 'source_quote': r.source_quote, 'priority': r.priority.value,
                                          'status': r.status.value} for r in analysis.requirements],
                           validation_issues=analysis.completeness_issues + analysis.classification_issues + analysis.evidence_issues)
            except TimeoutError:
                row['error'] = 'Per-variant wall-clock budget exceeded; this case is incomplete.'
            except AIProviderError as exc:
                row['error'] = str(exc)[:1000]
            finally:
                row['wall_ms'] = round((time.perf_counter() - case_start) * 1000, 1)
                calls = [dict(call) for call in provider.call_metrics]
                row['calls'] = calls
                row['call_count'] = len(calls)
                known = all(isinstance(c.get('prompt_tokens'), int) and isinstance(c.get('completion_tokens'), int) for c in calls)
                row['complete_usage'] = known
                row['input_tokens'] = sum(c['prompt_tokens'] for c in calls) if known else None
                row['output_tokens'] = sum(c['completion_tokens'] for c in calls) if known else None
                row['recovery_calls'] = calls[-1].get('recovery_calls') if calls else 0
                row['additional_calls_over_initial_plan'] = max(0, len(calls) - row['planned_initial_batches']) if 'planned_initial_batches' in row else None
                totals = defaultdict(lambda: {'characters': 0, 'bytes': 0})
                for request in composition:
                    for field, sizes in request['fields'].items():
                        for unit in ('characters', 'bytes'):
                            totals[field][unit] += sizes[unit]
                row['input_composition_totals'] = dict(totals)
                row['instruction_characters_total'] = sum(c['instruction_characters'] for c in composition)
                on_report(report)
        if len(offer['variants']) == 2:
            full, clean = offer['variants']
            offer['comparison'] = {
                'both_variants_passed': full['status'] == clean['status'] == 'ok',
                'input_token_delta': clean['input_tokens'] - full['input_tokens'] if full['input_tokens'] is not None and clean['input_tokens'] is not None else None,
                'wall_ms_delta': round(clean['wall_ms'] - full['wall_ms'], 1),
                'warning': 'Do not treat lower token use as an improvement if a variant failed or omitted qualifications.',
            }
    report['attempted_model_calls'] = attempted
    report['wall_ms'] = round((time.perf_counter() - started) * 1000, 1)
    on_report(report)
    return report
