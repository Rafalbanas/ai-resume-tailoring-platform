"""Request-independent, truth-checked draft export shared by web and FIFO jobs."""
import logging
import os
import tempfile
import time
from copy import copy
from pathlib import Path

from app.services.fact_validator import FactValidator
from app.services.processing import cpu_work_for_state
from app.services.summary_confirmation import account_context, confirmation_token, require_confirmation, summary_review

logger = logging.getLogger(__name__)


def prepare_draft_export(state, draft_id, *, summary_confirmed='', summary_token='', cv_name=''):
    # Re-read and revalidate in the worker too. A queued export cannot borrow a
    # confirmation from another draft/account or export a changed summary.
    job, response = state.storage.load_draft(draft_id)
    if job.workflow == 'custom' and cv_name.strip():
        job.cv_name = cv_name.strip()
    validator = FactValidator(state.profile, state.skills_bank, response.analysis,
                              review_key=state.settings.csrf_secret)
    result = validator.validate(response.resume, job)
    review = summary_review(result.resume, state.profile, state.settings.csrf_secret,
                            account_context(state.auth_store.username, 'draft', draft_id))
    require_confirmation(review, summary_confirmed, summary_token)
    # Use the same preparation as the synchronous export route.
    from app.services.resume_export import prepare_resume
    prepare_resume(result.resume, state.profile)
    return job, response, validator, result


async def export_draft(state, draft_id, *, template_name='ats_classic', summary_confirmed='', summary_token='', cv_name=''):
    started = time.perf_counter()
    state.resource_budget.check_disk()
    job, response, validator, result = prepare_draft_export(state, draft_id,
        summary_confirmed=summary_confirmed, summary_token=summary_token, cv_name=cv_name)
    guide = {}
    fitted, layout_warnings = await cpu_work_for_state(state, state.pdf_generator.fit_resume,
        result.resume, state.profile, guide, template_name=template_name,
        job_text=f'{job.role}\n{job.relevance_text}', one_page=template_name == 'modern_sidebar', fact_validator=validator)
    review = summary_review(fitted, state.profile, state.settings.csrf_secret,
                            account_context(state.auth_store.username, 'draft', draft_id))
    require_confirmation(review, summary_confirmed, summary_token)
    photo_enabled = template_name == 'modern_sidebar' and state.profile_photo.exists()
    # Render into a private temporary directory, not a visible saved application.
    # A DOCX failure/timeout must not leave a PDF-only CV in History or link a
    # draft to an incomplete application. Keep staging on the same filesystem.
    with tempfile.TemporaryDirectory(prefix='.export-', dir=state.storage.generated_dir) as temporary:
        staged = Path(temporary)
        await cpu_work_for_state(state, state.pdf_generator.generate, fitted, state.profile, staged / 'resume.pdf', guide,
            template_name=template_name, photo_enabled=photo_enabled)
        await cpu_work_for_state(state, state.docx_generator, fitted, state.profile, staged / 'resume.docx',
            photo_path=state.profile_photo.path, photo_enabled=photo_enabled, template_name=template_name)
        # Recheck after generation: queued work must not borrow stale admission
        # from the original HTTP request or an earlier offer in this batch.
        state.resource_budget.check_disk()
        staged_storage = copy(state.storage)
        staged_storage.generated_dir = staged / 'applications'
        staged_storage.generated_dir.mkdir()
        slug, folder = staged_storage.save_application(job, response.analysis, fitted, result.warnings, guide, draft_id,
            template_name=template_name, photo_enabled=photo_enabled, truth_lock_warnings=result.warnings,
            layout_warnings=layout_warnings, pre_fit_resume=result.resume,
            provider_used=getattr(response, 'provider_used', 'unknown'), model_used=getattr(response, 'model_used', 'unknown'),
            fallback_used=getattr(response, 'fallback_used', False), fallback_reason=getattr(response, 'fallback_reason', None),
            retrieval_context=response.retrieval_context)
        os.replace(staged / 'resume.pdf', folder / 'resume.pdf')
        os.replace(staged / 'resume.docx', folder / 'resume.docx')
        folder.chmod(0o700)
        staged_storage.mark_export_checked(slug)
        # Reserve a unique final name without replacing an existing document.
        # Metadata and artifacts become visible together via one directory rename.
        base_slug, counter = slug, 2
        while True:
            destination = state.storage.generated_dir / slug
            try:
                destination.mkdir(mode=0o700)
                break
            except FileExistsError:
                slug = f'{base_slug}_{counter}'
                counter += 1
        try:
            if review['required']:
                staged_storage.confirm_summary(base_slug, confirmation_token(fitted, state.profile, state.settings.csrf_secret,
                    account_context(state.auth_store.username, 'saved', slug)))
            state.resource_budget.check_disk()
            os.replace(folder, destination)
        except BaseException:
            destination.rmdir()  # Only our own empty reservation, never an existing CV.
            raise
    logger.info('Resume generated', extra={'stage': 'generate',
        'duration_ms': int((time.perf_counter() - started) * 1000), 'warning_count': len(result.warnings)})
    return slug
