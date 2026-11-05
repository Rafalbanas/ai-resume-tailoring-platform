"""Sequential, bounded batch orchestration; each offer retains a normal tailor task."""
import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from app.models.batch import BatchRequest
from app.models.job import JobRequest
from app.services.draft_export import export_draft
from app.services.task_manager import TaskKind, TaskRecord, TaskStatus

logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat()


async def run_batch(manager, task, state):
    spec = BatchRequest.model_validate(task.payload['batch'])
    items = [{'url': url, 'status': 'queued'} for url in spec.urls]

    def persist():
        current = manager.get_task(task.task_id) or task
        current.result = {'items': items, 'history_url': '/history', 'redirect_url': '/history'}
        manager._save_task(current)

    persist()
    for index, item in enumerate(items):
        child = None
        item['status'] = 'running'
        manager.update_task_progress(task.task_id, f'Offer {index + 1}/{len(items)}', int(index / len(items) * 100))
        persist()
        try:
            async with asyncio.timeout(manager.budget_seconds):
                state.resource_budget.check_disk()
                extracted = await state.job_extractor.extract(item['url'])
                item['offer_valid_until'] = extracted.offer_valid_until.isoformat() if extracted.offer_valid_until else None
                if extracted.extraction_method == 'manual_required':
                    item.update(status='manual_required', error=extracted.failure_reason or 'description_unavailable')
                    continue
                job = JobRequest(company=extracted.company or 'Unknown company', role=extracted.role or 'Job offer',
                                 job_url=item['url'], job_description=extracted.job_description,
                                 offer_valid_until=extracted.offer_valid_until,
                                 tailoring_level=spec.tailoring_level)
                child = TaskRecord(task_id=uuid4().hex, kind=TaskKind.TAILOR,
                    idempotency_key=f'batch:{task.task_id}:{index}', status=TaskStatus.RUNNING,
                    created_at=now(), started_at=now(), keep_history=True,
                    payload={'job': job.model_dump(mode='json'), 'llm_provider': spec.llm_provider,
                             'ollama_model': spec.ollama_model, 'ollama_context': spec.ollama_context,
                             'gemini_model': spec.gemini_model, 'allow_fallback': spec.allow_fallback})
                manager._save_task(child)
                item['task_id'] = child.task_id
                # Normal provider selection, validators, diagnostics, draft storage and token tracking.
                await manager._execute_task(child, state)
                child = manager.get_task(child.task_id)
                item.update(child.result)
                item['analysis_url'] = f"/analysis/{child.result['draft_id']}"
                item['status'] = 'draft_ready'
                persist()
                if spec.export:
                    try:
                        async with state.resource_budget.mutation_slots:
                            slug = await export_draft(state, child.result['draft_id'], template_name=spec.template_name,
                                                      require_reliable_analysis=True)
                        item.update(status='completed', slug=slug, preview_url=f'/preview/{slug}',
                                    pdf_url=f'/download/{slug}/pdf', docx_url=f'/download/{slug}/docx')
                    except (ValueError, HTTPException) as exc:
                        # Never auto-confirm an AI summary or weaken Truth Lock/layout checks.
                        item.update(status='review_required', error=str(exc.detail) if isinstance(exc, HTTPException) else str(exc))
        except asyncio.CancelledError:
            item.update(status='failed', error='Processing interrupted; saved results remain available.')
            raise
        except Exception as exc:
            logger.warning('Batch %s item %s failed (%s)', task.task_id, index, type(exc).__name__)
            message = ('Offer execution deadline exceeded; retry this URL.' if isinstance(exc, TimeoutError)
                       else 'Offer processing failed; retry this URL or inspect its saved analysis.')
            item.update(status='failed', error=message)
            if child and not item.get('draft_id'):
                child = manager.get_task(child.task_id) or child
                child.status = TaskStatus.FAILED
                child.completed_at = now()
                child.error = item['error']
                manager._save_task(child)
        finally:
            if child:
                current_child = manager.get_task(child.task_id) or child
                if current_child.status == TaskStatus.RUNNING:
                    current_child.status = TaskStatus.FAILED
                    current_child.completed_at = now()
                    current_child.error = item.get('error', 'Processing interrupted')
                    manager._save_task(current_child)
            persist()
    current = manager.get_task(task.task_id) or task
    current.status = TaskStatus.COMPLETED
    current.stage = 'Batch finished — inspect individual offer results'
    current.progress_percent = 100
    current.completed_at = now()
    current.execution_duration_seconds = round((datetime.now(timezone.utc) - datetime.fromisoformat(current.started_at)).total_seconds(), 2)
    manager._save_task(current)
