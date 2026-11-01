"""Request-independent, truth-checked draft export shared by web and FIFO jobs."""
import logging
import time

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
    slug, folder = state.storage.save_application(job, response.analysis, fitted, result.warnings, guide, draft_id,
        template_name=template_name, photo_enabled=photo_enabled, truth_lock_warnings=result.warnings,
        layout_warnings=layout_warnings, pre_fit_resume=result.resume,
        provider_used=getattr(response, 'provider_used', 'unknown'), model_used=getattr(response, 'model_used', 'unknown'),
        fallback_used=getattr(response, 'fallback_used', False), fallback_reason=getattr(response, 'fallback_reason', None),
        retrieval_context=response.retrieval_context)
    await cpu_work_for_state(state, state.pdf_generator.generate, fitted, state.profile, folder / 'resume.pdf', guide,
        template_name=template_name, photo_enabled=photo_enabled)
    await cpu_work_for_state(state, state.docx_generator, fitted, state.profile, folder / 'resume.docx',
        photo_path=state.profile_photo.path, photo_enabled=photo_enabled, template_name=template_name)
    state.storage.mark_export_checked(slug)
    if review['required']:
        state.storage.confirm_summary(slug, confirmation_token(fitted, state.profile, state.settings.csrf_secret,
            account_context(state.auth_store.username, 'saved', slug)))
    logger.info('Resume generated', extra={'stage': 'generate',
        'duration_ms': int((time.perf_counter() - started) * 1000), 'warning_count': len(result.warnings)})
    return slug
