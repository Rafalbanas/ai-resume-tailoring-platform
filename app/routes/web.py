import json
import logging
import re
import secrets
import time
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.core.security import new_csrf_token, require_session, validate_csrf
from app.models.candidate import Interest
from app.models.job import JobExtraction, JobRequest, JobTextRequest, JobUrlRequest
from app.models.resume import TailoredResume
from app.models.skills import SkillEvidence, VerifiedSkill
from app.services.ai_provider import AIProviderError
from app.services.artifact_transaction import commit_artifacts, staged_artifacts
from app.services.evidence_gaps import evidence_questions
from app.services.fact_catalog import FactCatalog
from app.services.fact_validator import FactValidator
from app.services.processing import cpu_work
from app.services.profile_loader import save_master_profile
from app.services.profile_photo import ProfilePhotoError
from app.services.resume_editor import apply_resume_edits
from app.services.resume_export import prepare_resume
from app.services.storage import compute_pre_fit_diff
from app.services.summary_confirmation import account_context, confirmation_token, require_confirmation, summary_review
from app.services.task_manager import TaskKind, TaskStatus, compute_idempotency_key
from app.services.ui_language import ui_text

router = APIRouter()
logger = logging.getLogger(__name__)


def context(request: Request, **values):
    return {
        "request": request,
        "account_username": request.app.state.auth_store.username if getattr(request.state, "authenticated", False) else "",
        "app_root_path": request.scope.get("root_path", ""),
        "engine_primary": getattr(getattr(request.app.state, "settings", None), "active_llm_provider", "unknown"),
        "engine_fallback": "gemini" if request.app.state.provider.fallback_enabled else "none",
        "fallback_enabled": request.app.state.provider.fallback_enabled,
        "demo_mode": request.app.state.settings.demo_mode,
        "ollama_model": getattr(getattr(request.app.state, "settings", None), "ollama_model", "unknown"),
        "gemini_model": getattr(getattr(request.app.state, "settings", None), "gemini_model", "unknown"),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "asset_version": getattr(getattr(request.app.state, "settings", None), "app_build_sha", ""),
        **values,
    }


def limit_request(request):
    if not getattr(request.state, 'rate_checked', False):
        request.app.state.limiter.check(request.client.host if request.client else 'unknown')
        request.state.rate_checked = True


def guard(request: Request) -> None:
    require_session(request)


def _skill_id(name: str) -> str:
    return "skill_" + "_".join(re.findall(r"[a-z0-9]+", name.casefold()))


def _evidence_options(request: Request) -> list[dict[str, str]]:
    return request.app.state.skills_bank.catalog.for_prompt()


def _skill_from_form(form, existing: VerifiedSkill | None = None) -> VerifiedSkill:
    evidence = list(existing.evidence) if existing else []
    source_type = str(form.get("evidence_source_type", "")).strip()
    source_id = str(form.get("evidence_source_id", "")).strip()
    description = str(form.get("evidence_description", "")).strip()
    if source_type and source_id and description:
        if source_type == "manual_verified" and form.get("manual_confirm") != "on":
            raise ValueError("Manual verification must be explicitly confirmed.")
        evidence.append(SkillEvidence(source_type=source_type, source_id=source_id, description=description))
    name = str(form.get("name", "")).strip()
    aliases = [item.strip() for item in str(form.get("aliases", "")).replace(",", "\n").splitlines() if item.strip()]
    return VerifiedSkill(
        id=existing.id if existing else _skill_id(name), name=name,
        category=str(form.get("category", "")).strip(), subcategory=str(form.get("subcategory", "")).strip(),
        level=str(form.get("level", "basic")), verified=form.get("verified") == "on",
        allowed_in_cv=form.get("allowed_in_cv") == "on", enabled=existing.enabled if existing else True,
        priority=int(form.get("priority", 5)), aliases=aliases, evidence=evidence,
        notes=str(form.get("notes", "")).strip(), cv_wording=str(form.get("cv_wording", "")).strip(),
    )


@router.post("/api/extract-job-url", response_model=JobExtraction)
async def extract_job_url(request: Request, payload: JobUrlRequest):
    guard(request)
    limit_request(request)
    validate_csrf(
        request.headers.get("X-CSRF-Token", ""),
        request.cookies.get(request.app.state.settings.csrf_cookie_name, ""),
        request.app.state.settings.csrf_secret,
    )
    result = await request.app.state.job_extractor.extract(payload.url)
    if result.extraction_method == "manual_required":
        logger.info("Job URL requires manual input", extra={"stage": "job_extract"})
    else:
        logger.info("Job URL extracted", extra={"stage": "job_extract", "method": result.extraction_method})
    return result


@router.post("/api/clean-job-text", response_model=JobExtraction)
async def clean_job_text(request: Request, payload: JobTextRequest):
    guard(request)
    limit_request(request)
    validate_csrf(request.headers.get("X-CSRF-Token", ""),
                  request.cookies.get(request.app.state.settings.csrf_cookie_name, ""),
                  request.app.state.settings.csrf_secret)
    from app.services.job_extractors.pasted import clean_pasted_offer

    candidate = clean_pasted_offer(payload.text, payload.url)
    return request.app.state.job_extractor._result(candidate, payload.url, "html" if candidate.usable else "manual_required")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, from_task: str | None = None):
    guard(request)
    default_provider = getattr(request.app.state.settings, "active_llm_provider", "ollama")
    form_data = {
        "company": "",
        "role": "",
        "job_description": "",
        "job_url": "",
        "llm_provider": default_provider,
    }
    if from_task:
        task = request.app.state.task_manager.get_task(from_task)
        if task and task.payload:
            job_payload = task.payload.get("job", {})
            form_data["company"] = job_payload.get("company", "")
            form_data["role"] = job_payload.get("role", "")
            form_data["job_description"] = job_payload.get("job_description", "")
            form_data["job_url"] = job_payload.get("job_url", "")
            form_data["llm_provider"] = task.payload.get("llm_provider", default_provider)

    return request.app.state.templates.TemplateResponse(
        request=request, name="index.html", context=context(request, **form_data)
    )


@router.post("/analyze")
async def analyze(
    request: Request,
    company: Annotated[str, Form()],
    role: Annotated[str, Form()],
    job_description: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    job_url: Annotated[str, Form()] = "",
    llm_provider: Annotated[str, Form()] = "auto",
):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    if len(job_description) > request.app.state.settings.max_job_description_chars:
        raise HTTPException(status_code=413, detail="Job description is too long")
    try:
        job = JobRequest(company=company, role=role, job_url=job_url or None, job_description=job_description)
    except ValidationError:
        return request.app.state.templates.TemplateResponse(
            request=request, name="index.html",
            context=context(
                request,
                error="Check the form fields and paste a complete job description.",
                company=company,
                role=role,
                job_description=job_description,
                job_url=job_url,
                llm_provider=llm_provider,
            ),
            status_code=422,
        )

    # Compute idempotency key to prevent duplicate runs on rapid clicks or retries
    key = compute_idempotency_key(
        "tailor",
        company=company.strip(),
        role=role.strip(),
        job_description=job_description.strip(),
        job_url=job_url.strip(),
        llm_provider=llm_provider.strip(),
    )

    task = await run_in_threadpool(request.app.state.task_manager.find_active_by_idempotency_key, key)
    if not task:
        task = request.app.state.task_manager.create_task(
            kind=TaskKind.TAILOR,
            payload={
                "job": job.model_dump(mode="json"),
                "llm_provider": llm_provider,
            },
            idempotency_key=key,
        )

    accept = request.headers.get("accept", "")
    is_xhr = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if "application/json" in accept or is_xhr:
        return JSONResponse(
            status_code=202,
            content={
                "task_id": task.task_id,
                "status": task.status.value,
                "status_url": f"/tasks/{task.task_id}",
                "view_url": f"/tasks/{task.task_id}/view",
            },
        )

    response = request.app.state.templates.TemplateResponse(
        request=request, name="task_progress.html",
        context=context(request, task=task),
        status_code=202,
    )
    response.headers["Location"] = f"/tasks/{task.task_id}/view"
    response.headers["X-Task-ID"] = task.task_id
    return response


@router.get("/tasks/{task_id}")
async def get_task_status(request: Request, task_id: str):
    guard(request)
    task = request.app.state.task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    payload = task.model_dump(mode="json")
    payload["stage"] = ui_text(task.stage)
    payload["error"] = ui_text(task.error) if task.error else None
    return JSONResponse(content=payload)


@router.get("/tasks/{task_id}/view", response_class=HTMLResponse)
async def task_progress_view(request: Request, task_id: str):
    guard(request)
    task = request.app.state.task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status == TaskStatus.COMPLETED and task.result and task.result.get("redirect_url"):
        return RedirectResponse(url=task.result["redirect_url"], status_code=303)
    return request.app.state.templates.TemplateResponse(
        request=request, name="task_progress.html",
        context=context(request, task=task),
    )


@router.post("/tasks/{task_id}/retry")
async def retry_task(
    request: Request,
    task_id: str,
    csrf_token: Annotated[str, Form()] = "",
):
    guard(request)
    limit_request(request)
    if csrf_token:
        validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)

    task = request.app.state.task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # If the task is still running or queued, redirect directly to avoid duplicate creation
    if task.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
        return RedirectResponse(url=f"/tasks/{task.task_id}/view", status_code=303)

    # Check for another active task sharing the same idempotency key
    active_task = await run_in_threadpool(request.app.state.task_manager.find_active_by_idempotency_key, task.idempotency_key)
    if active_task:
        return RedirectResponse(url=f"/tasks/{active_task.task_id}/view", status_code=303)

    retry_key = compute_idempotency_key(
        task.kind.value,
        retry_from=task.task_id,
        attempt=str(time.time()),
    )
    new_task = request.app.state.task_manager.create_task(
        kind=task.kind,
        payload=task.payload,
        idempotency_key=retry_key,
    )

    accept = request.headers.get("accept", "")
    is_xhr = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if "application/json" in accept or is_xhr:
        return JSONResponse(
            status_code=202,
            content={
                "task_id": new_task.task_id,
                "status": new_task.status.value,
                "status_url": f"/tasks/{new_task.task_id}",
                "view_url": f"/tasks/{new_task.task_id}/view",
            },
        )

    return RedirectResponse(url=f"/tasks/{new_task.task_id}/view", status_code=303)



@router.get("/analysis/{draft_id}", response_class=HTMLResponse)
async def analysis_view(request: Request, draft_id: str):
    guard(request)
    try:
        job, response = request.app.state.storage.load_draft(draft_id)
    except (FileNotFoundError, json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=404, detail="Draft not found") from exc
    checked = FactValidator(request.app.state.profile, request.app.state.skills_bank, response.analysis,
        review_key=request.app.state.settings.csrf_secret).validate(response.resume, job).resume
    review = summary_review(checked, request.app.state.profile, request.app.state.settings.csrf_secret,
        account_context(request.app.state.auth_store.username, 'draft', draft_id))
    return request.app.state.templates.TemplateResponse(
        request=request, name="analysis.html",
        context=context(
            request,
            job=job,
            analysis=response.analysis,
            token_usage=response.token_usage,
            evidence_questions=evidence_questions(response.analysis),
            draft_id=draft_id,
            summary_review=review,
            provider_used=getattr(response, "provider_used", "unknown"),
            model_used=getattr(response, "model_used", "unknown"),
            fallback_used=getattr(response, "fallback_used", False),
            fallback_reason=getattr(response, "fallback_reason", None),
        ),
    )


@router.post("/analysis/{draft_id}/evidence")
async def save_analysis_evidence(request: Request, draft_id: str):
    guard(request)
    form = await request.form()
    validate_csrf(str(form.get("csrf_token", "")), request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    from app.services.evidence_gaps import answer_fact, evidence_questions
    from app.services.profile_enrichment import apply_enrichment
    try:
        _, response = request.app.state.storage.load_draft(draft_id)
        question = next((q for q in evidence_questions(response.analysis) if q["id"] == form.get("question_id")), None)
        if question is None:
            raise ValueError("This question is not a current evidence gap.")
        fact = answer_fact(question, str(form.get("answer", "")), str(form.get("scope", "")),
                           str(form.get("experience_context", "")), str(form.get("details", "")),
                           consent=form.get("save_consent") == "on")
        apply_enrichment(request.app.state.settings.data_dir, {"summary_facts": [fact]})
        from app.services.profile_loader import load_master_profile
        profile, status = load_master_profile(request.app.state.settings)
        request.app.state.profile, request.app.state.profile_status = profile, status
        # Providers hold this bank object: update it in place so later analyses
        # use the saved facts without a restart or a separate scoring system.
        request.app.state.skills_bank.profile = profile
        request.app.state.skills_bank.catalog = FactCatalog(profile)
    except (ValueError, FileNotFoundError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"{request.scope.get('root_path', '')}/analysis/{draft_id}?evidence_saved=1", status_code=303)


@router.post("/generate/{draft_id}")
async def generate(request: Request, draft_id: str, csrf_token: Annotated[str, Form()],
                   template_name: Annotated[Literal["modern_sidebar", "ats_classic"], Form()] = "ats_classic",
                   summary_confirmed: Annotated[str, Form()] = '', summary_token: Annotated[str, Form()] = ''):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    try:
        job, response = request.app.state.storage.load_draft(draft_id)
    except (FileNotFoundError, json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=404, detail="Draft not found") from exc
    if not response.analysis.is_reliable:
        raise HTTPException(status_code=409, detail="Analysis has no verified requirements. Review the job and retry before generating a tailored CV.")
    started = time.perf_counter()
    validator = FactValidator(request.app.state.profile, request.app.state.skills_bank, response.analysis, review_key=request.app.state.settings.csrf_secret)
    result = validator.validate(response.resume, job)
    review = summary_review(result.resume, request.app.state.profile, request.app.state.settings.csrf_secret,
        account_context(request.app.state.auth_store.username, 'draft', draft_id))
    require_confirmation(review, summary_confirmed, summary_token)
    try:
        prepare_resume(result.resume, request.app.state.profile)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    layout_guide = {}
    try:
        fitted_resume, layout_warnings = await cpu_work(request, request.app.state.pdf_generator.fit_resume,
            result.resume, request.app.state.profile, layout_guide, template_name=template_name,
            job_text=f"{job.role}\n{job.job_description}",
            one_page=template_name == "modern_sidebar", fact_validator=validator,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    warnings = result.warnings
    final_review = summary_review(fitted_resume, request.app.state.profile, request.app.state.settings.csrf_secret,
        account_context(request.app.state.auth_store.username, 'draft', draft_id))
    require_confirmation(final_review, summary_confirmed, summary_token)
    photo_enabled = template_name == "modern_sidebar" and request.app.state.profile_photo.exists()
    slug, folder = request.app.state.storage.save_application(
        job,
        response.analysis,
        fitted_resume,
        warnings,
        layout_guide,
        draft_id,
        template_name=template_name,
        photo_enabled=photo_enabled,
        truth_lock_warnings=result.warnings,
        layout_warnings=layout_warnings,
        pre_fit_resume=result.resume,
        provider_used=getattr(response, "provider_used", "unknown"),
        model_used=getattr(response, "model_used", "unknown"),
        fallback_used=getattr(response, "fallback_used", False),
        fallback_reason=getattr(response, "fallback_reason", None),
    )
    await cpu_work(request, request.app.state.pdf_generator.generate,
        fitted_resume,
        request.app.state.profile,
        folder / "resume.pdf",
        layout_guide,
        template_name=template_name,
        photo_enabled=photo_enabled,
    )
    await cpu_work(request, request.app.state.docx_generator,
        fitted_resume,
        request.app.state.profile,
        folder / "resume.docx",
        photo_path=request.app.state.profile_photo.path,
        photo_enabled=photo_enabled,
        template_name=template_name,
    )
    request.app.state.storage.mark_export_checked(slug)
    if final_review['required']:
        request.app.state.storage.confirm_summary(slug, confirmation_token(
            fitted_resume, request.app.state.profile, request.app.state.settings.csrf_secret,
            account_context(request.app.state.auth_store.username, 'saved', slug)))
    logger.info(
        "Resume generated",
        extra={
            "stage": "generate",
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "warning_count": len(warnings),
        },
    )
    return RedirectResponse(f"/preview/{slug}", status_code=303)


@router.get("/preview/{slug}", response_class=HTMLResponse)
async def preview(request: Request, slug: str):
    guard(request)
    try:
        _, resume, _, metadata = request.app.state.storage.load_application(slug)
    except (OSError, ValidationError, json.JSONDecodeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Resume not found") from exc
    resume_html = await cpu_work(request, request.app.state.pdf_generator.render_preview,
        resume,
        request.app.state.profile,
        metadata.get("layout_guide"),
        template_name=metadata.get("template_name", "modern_sidebar"),
        photo_enabled=metadata.get("photo_enabled", request.app.state.profile_photo.exists()),
        interactive_photo=metadata.get("template_name", "modern_sidebar") == "modern_sidebar",
    )
    pre_fit = request.app.state.storage.load_pre_fit_resume(slug)
    pre_fit_diff = compute_pre_fit_diff(pre_fit, resume)
    return request.app.state.templates.TemplateResponse(
        request=request, name="resume_preview.html",
        context=context(
            request,
            slug=slug,
            metadata=metadata,
            resume_html=resume_html,
            photo_available=request.app.state.profile_photo.exists(),
            pre_fit_diff=pre_fit_diff,
            summary_review=summary_review(resume, request.app.state.profile, request.app.state.settings.csrf_secret,
                account_context(request.app.state.auth_store.username, 'saved', slug), metadata.get('summary_confirmation', '')),
        ),
    )


def _refresh_photo_artifacts(request: Request, slug: str, *, photo_enabled: bool, template_name: str | None = None) -> bool:
    """Refresh only presentation artifacts; resume text and generated baseline stay untouched."""
    try:
        _, resume, _, metadata = request.app.state.storage.load_application(slug)
    except (OSError, ValidationError, json.JSONDecodeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Resume not found") from exc
    template_name = template_name or metadata.get("template_name", "modern_sidebar")
    enabled = bool(
        photo_enabled and template_name == "modern_sidebar" and request.app.state.profile_photo.exists()
    )
    folder = request.app.state.storage.application_folder(slug)
    with staged_artifacts(folder) as staged:
        request.app.state.pdf_generator.generate(
            resume, request.app.state.profile, staged / "resume.pdf", metadata.get("layout_guide"),
            template_name=template_name, photo_enabled=enabled,
        )
        request.app.state.docx_generator(
            resume, request.app.state.profile, staged / "resume.docx",
            photo_path=request.app.state.profile_photo.path, photo_enabled=enabled,
            template_name=template_name,
        )
        commit_artifacts(folder, staged, lambda: request.app.state.storage.update_presentation(slug, photo_enabled=enabled, template_name=template_name,
            modern_photo_enabled=photo_enabled if template_name == "modern_sidebar" else metadata.get("modern_photo_enabled", metadata.get("photo_enabled", False))))
    return enabled


def _validate_ajax_csrf(request: Request) -> None:
    validate_csrf(
        request.headers.get("X-CSRF-Token", ""),
        request.cookies.get(request.app.state.settings.csrf_cookie_name, ""),
        request.app.state.settings.csrf_secret,
    )


def _save_and_refresh_photo(request, slug, filename, mime, content, *, crop_x, crop_y, crop_zoom):
    request.app.state.profile_photo.save(filename, mime, content, crop_x=crop_x, crop_y=crop_y, crop_zoom=crop_zoom)
    return _refresh_photo_artifacts(request, slug, photo_enabled=True)


def _remove_and_refresh_photo(request, slug):
    request.app.state.profile_photo.remove()
    return _refresh_photo_artifacts(request, slug, photo_enabled=False)


@router.post("/preview/{slug}/photo")
async def upload_preview_photo(
    request: Request,
    slug: str,
    photo: Annotated[UploadFile, File()],
    crop_x: Annotated[float, Form()] = 50.0,
    crop_y: Annotated[float, Form()] = 50.0,
    crop_zoom: Annotated[float, Form()] = 1.0,
):
    guard(request)
    limit_request(request)
    _validate_ajax_csrf(request)
    try:
        request.app.state.storage.application_folder(slug)
        content = await photo.read(request.app.state.settings.profile_photo_max_bytes + 1)
        enabled = await cpu_work(request, _save_and_refresh_photo, request, slug,
            photo.filename or "photo", photo.content_type or "", content,
            crop_x=crop_x, crop_y=crop_y, crop_zoom=crop_zoom)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Resume not found") from exc
    except ProfilePhotoError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error uploading profile photo")
        return JSONResponse({"ok": False, "error": "Could not read this image."}, status_code=422)
    finally:
        await photo.close()
    return {"ok": True, "photo_enabled": enabled}


@router.post("/preview/{slug}/photo/use")
async def use_preview_photo(request: Request, slug: str):
    guard(request)
    limit_request(request)
    _validate_ajax_csrf(request)
    if not request.app.state.profile_photo.exists():
        return JSONResponse({"ok": False, "error": "No saved profile photo is available."}, status_code=404)
    return {"ok": True, "photo_enabled": await cpu_work(request, _refresh_photo_artifacts, request, slug, photo_enabled=True)}


@router.post("/preview/{slug}/photo/hide")
async def hide_preview_photo(request: Request, slug: str):
    guard(request)
    limit_request(request)
    _validate_ajax_csrf(request)
    await cpu_work(request, _refresh_photo_artifacts, request, slug, photo_enabled=False)
    return {"ok": True, "photo_enabled": False}


@router.post("/preview/{slug}/photo/remove")
async def remove_preview_photo(request: Request, slug: str):
    guard(request)
    limit_request(request)
    _validate_ajax_csrf(request)
    await cpu_work(request, _remove_and_refresh_photo, request, slug)
    return {"ok": True, "photo_enabled": False}


@router.get("/edit/{slug}", response_class=HTMLResponse)
async def edit_resume(request: Request, slug: str):
    guard(request)
    try:
        job, resume, _, metadata = request.app.state.storage.load_application(slug)
    except (OSError, ValidationError, json.JSONDecodeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Resume not found") from exc
    return request.app.state.templates.TemplateResponse(
        request=request, name="resume_edit.html",
        context=context(request, slug=slug, metadata=metadata, resume=resume,
                existing_warnings=FactValidator(request.app.state.profile, request.app.state.skills_bank, review_key=request.app.state.settings.csrf_secret).validate_manual_edit(resume, resume, job).warnings),
    )


def _regenerate_artifacts(
    request: Request,
    slug: str,
    job: JobRequest,
    resume: TailoredResume,
    *,
    template_name: str = "modern_sidebar",
    photo_enabled: bool = False,
    validated_edit=None,
) -> list[str]:
    result = validated_edit or FactValidator(request.app.state.profile, request.app.state.skills_bank, review_key=request.app.state.settings.csrf_secret).validate(resume, job, preserve_skills=True)
    layout_guide = request.app.state.reference_library.layout_guide()
    fitted_resume, layout_warnings = request.app.state.pdf_generator.fit_resume(
        result.resume, request.app.state.profile, layout_guide, template_name=template_name,
        job_text=f"{job.role}\n{job.job_description}",
    )
    if validated_edit is not None and fitted_resume != result.resume:
        raise ValueError("Resume layout: the selected layout would change saved content. Choose ATS Classic to preserve every edited section.")
    warnings = result.warnings + layout_warnings
    metadata = request.app.state.storage.load_application(slug)[3]
    modern_photo_preference = photo_enabled if template_name == "modern_sidebar" else metadata.get("modern_photo_enabled", metadata.get("photo_enabled", False))
    photo_enabled = bool(
        photo_enabled and template_name == "modern_sidebar" and request.app.state.profile_photo.exists()
    )
    folder = request.app.state.storage.application_folder(slug)
    with staged_artifacts(folder) as staged:
        request.app.state.pdf_generator.generate(
            fitted_resume, request.app.state.profile, staged / "resume.pdf", layout_guide,
            template_name=template_name, photo_enabled=photo_enabled,
        )
        request.app.state.docx_generator(
            fitted_resume, request.app.state.profile, staged / "resume.docx",
            photo_path=request.app.state.profile_photo.path, photo_enabled=photo_enabled,
            template_name=template_name,
        )
        commit_artifacts(folder, staged, lambda: request.app.state.storage.save_current_resume(
            slug, fitted_resume, warnings, template_name=template_name, photo_enabled=photo_enabled,
            truth_lock_warnings=result.warnings, layout_warnings=layout_warnings, modern_photo_enabled=modern_photo_preference,
        ))
    return warnings


@router.post("/edit/{slug}")
async def save_resume_edit(request: Request, slug: str):
    guard(request)
    limit_request(request)
    form = await request.form()
    validate_csrf(
        str(form.get("csrf_token", "")),
        request.cookies.get(request.app.state.settings.csrf_cookie_name, ""),
        request.app.state.settings.csrf_secret,
    )
    try:
        job, resume, _, metadata = request.app.state.storage.load_application(slug)
    except (OSError, ValidationError, json.JSONDecodeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Resume not found") from exc
    try:
        edited = apply_resume_edits(resume, form)
        template_name = str(form.get("template_name", "modern_sidebar"))
        if template_name not in {"modern_sidebar", "ats_classic"}:
            raise ValueError("Resume layout: unsupported selection. Choose Modern Sidebar or ATS Classic.")
        photo_enabled = form.get("photo_enabled") == "on"
        if edited == resume:
            # Presentation changes preserve the exact saved content, including legacy CVs.
            if template_name == "ats_classic":
                photo_enabled = metadata.get("modern_photo_enabled", metadata.get("photo_enabled", False))
            await cpu_work(request, _refresh_photo_artifacts, request, slug, photo_enabled=photo_enabled, template_name=template_name)
            return RedirectResponse(f"/preview/{slug}", status_code=303)
        checked = FactValidator(request.app.state.profile, request.app.state.skills_bank, review_key=request.app.state.settings.csrf_secret).validate_manual_edit(resume, edited, job)
        if checked.issues:
            return request.app.state.templates.TemplateResponse(
                request=request, name="resume_edit.html", context=context(request, slug=slug, metadata=metadata, resume=edited,
                edit_issues=checked.issues, existing_warnings=checked.warnings,
                error="The fields below were not saved. Other saved content has not been overwritten."),
                status_code=422,
            )
        await cpu_work(request, _regenerate_artifacts,
            request,
            slug,
            job,
            checked.resume,
            template_name=template_name,
            photo_enabled=photo_enabled,
            validated_edit=checked,
        )
    except (OSError, json.JSONDecodeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Resume not found") from exc
    except (ValidationError, ValueError) as exc:
        return request.app.state.templates.TemplateResponse(
            request=request, name="resume_edit.html",
            context=context(
                request,
                slug=slug,
                metadata=metadata,
                resume=edited if "edited" in locals() else resume,
                error="Changes were not saved. Review the field or layout issue below.",
                edit_issues=([{ "field": ".".join(map(str, e["loc"])), "reason": e["msg"], "suggestion": "Correct this field and save again." } for e in exc.errors()] if isinstance(exc, ValidationError) else [{"field": "PDF/DOCX export or save", "reason": str(exc), "suggestion": "Choose ATS Classic for pagination/layout errors; otherwise correct the reported export issue and retry. Saved files remain unchanged."}]),
            ),
            status_code=422,
        )
    return RedirectResponse(f"/preview/{slug}", status_code=303)


@router.post("/reset/{slug}")
async def reset_resume(request: Request, slug: str, csrf_token: Annotated[str, Form()]):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    try:
        job, _, generated, metadata = request.app.state.storage.load_application(slug)
        await cpu_work(request, _regenerate_artifacts,
            request,
            slug,
            job,
            generated,
            template_name=metadata.get("template_name", "modern_sidebar"),
            photo_enabled=metadata.get("photo_enabled", False),
        )
    except (OSError, ValidationError, json.JSONDecodeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Resume not found") from exc
    return RedirectResponse(f"/preview/{slug}", status_code=303)


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    guard(request)
    return request.app.state.templates.TemplateResponse(
        request=request, name="history.html", context=context(request, rows=request.app.state.storage.history())
    )


@router.post("/history/{slug}/delete")
async def delete_history_item(request: Request, slug: str, csrf_token: Annotated[str, Form()]):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    try:
        request.app.state.storage.delete_application(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Generated CV not found") from exc
    return RedirectResponse("/history", status_code=303)


@router.post("/history/clear")
async def clear_history(request: Request, csrf_token: Annotated[str, Form()]):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    request.app.state.storage.clear_history()
    return RedirectResponse("/history", status_code=303)


@router.get("/references", response_class=HTMLResponse)
async def references(request: Request):
    guard(request)
    return request.app.state.templates.TemplateResponse(
        request=request, name="references.html", context=context(request, references=request.app.state.reference_library.list())
    )


@router.post("/references/upload", response_class=HTMLResponse)
async def upload_references(
    request: Request,
    files: Annotated[list[UploadFile], File()],
    csrf_token: Annotated[str, Form()],
):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    errors = []
    for upload in files[:20]:
        try:
            content = await upload.read(request.app.state.settings.reference_cv_max_bytes + 1)
            await cpu_work(request, request.app.state.reference_library.upload, upload.filename or "reference", content)
        except ValueError as exc:
            errors.append(f"{upload.filename}: {exc}")
        finally:
            await upload.close()
    if errors:
        return request.app.state.templates.TemplateResponse(
            request=request, name="references.html",
            context=context(request, references=request.app.state.reference_library.list(), errors=errors),
            status_code=422,
        )
    return RedirectResponse("/references", status_code=303)


@router.post("/references/{reference_id}/remove")
async def remove_reference(request: Request, reference_id: str, csrf_token: Annotated[str, Form()]):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    try:
        request.app.state.reference_library.remove(reference_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Reference CV not found") from exc
    return RedirectResponse("/references", status_code=303)


@router.get("/skills", response_class=HTMLResponse)
async def skills(request: Request):
    guard(request)
    groups: dict[str, list[VerifiedSkill]] = {}
    for skill in request.app.state.skills_bank.skills:
        groups.setdefault(skill.category, []).append(skill)
    return request.app.state.templates.TemplateResponse(request=request, name="skills.html", context=context(request, groups=groups))


@router.get("/skills/new", response_class=HTMLResponse)
async def new_skill(request: Request):
    guard(request)
    return request.app.state.templates.TemplateResponse(
        request=request, name="skill_form.html", context=context(request, skill=None, evidence_options=_evidence_options(request))
    )


@router.get("/skills/{skill_id}/edit", response_class=HTMLResponse)
async def edit_skill(request: Request, skill_id: str):
    guard(request)
    skill = request.app.state.skills_bank.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return request.app.state.templates.TemplateResponse(
        request=request, name="skill_form.html", context=context(request, skill=skill, evidence_options=_evidence_options(request))
    )


@router.post("/skills/save", response_class=HTMLResponse)
async def save_skill(request: Request):
    guard(request)
    limit_request(request)
    form = await request.form()
    validate_csrf(str(form.get("csrf_token", "")), request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    existing_id = str(form.get("existing_id", "")).strip()
    existing = request.app.state.skills_bank.get(existing_id) if existing_id else None
    try:
        skill = _skill_from_form(form, existing)
        request.app.state.skills_bank.update(existing.id, skill) if existing else request.app.state.skills_bank.add(skill)
    except (ValueError, ValidationError, KeyError) as exc:
        return request.app.state.templates.TemplateResponse(
            request=request, name="skill_form.html", context=context(request, skill=existing, evidence_options=_evidence_options(request), error=str(exc)),
            status_code=422,
        )
    return RedirectResponse("/skills", status_code=303)


@router.post("/skills/{skill_id}/toggle")
async def toggle_skill(request: Request, skill_id: str, csrf_token: Annotated[str, Form()]):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    try:
        request.app.state.skills_bank.toggle(skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc
    return RedirectResponse("/skills", status_code=303)


@router.post("/skills/{skill_id}/delete")
async def delete_skill(request: Request, skill_id: str, csrf_token: Annotated[str, Form()]):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    try:
        request.app.state.skills_bank.delete(skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc
    return RedirectResponse("/skills", status_code=303)


@router.get("/skills/{skill_id}/evidence", response_class=HTMLResponse)
async def skill_evidence(request: Request, skill_id: str):
    guard(request)
    skill = request.app.state.skills_bank.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return request.app.state.templates.TemplateResponse(
        request=request, name="skill_evidence.html", context=context(request, skill=skill, evidence_options=_evidence_options(request))
    )


@router.post("/skills/{skill_id}/evidence")
async def add_skill_evidence(request: Request, skill_id: str):
    guard(request)
    limit_request(request)
    form = await request.form()
    validate_csrf(str(form.get("csrf_token", "")), request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    try:
        source_type = str(form.get("source_type", ""))
        if source_type == "manual_verified" and form.get("manual_confirm") != "on":
            raise ValueError("Manual verification must be explicitly confirmed.")
        request.app.state.skills_bank.add_evidence(skill_id, SkillEvidence(
            source_type=source_type, source_id=str(form.get("source_id", "")),
            description=str(form.get("description", "")),
        ))
    except (ValueError, ValidationError, KeyError) as exc:
        skill = request.app.state.skills_bank.get(skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found") from exc
        return request.app.state.templates.TemplateResponse(
            request=request, name="skill_evidence.html", context=context(request, skill=skill, evidence_options=_evidence_options(request), error=str(exc)),
            status_code=422,
        )
    return RedirectResponse(f"/skills/{skill_id}/evidence", status_code=303)


@router.post("/skills/{skill_id}/evidence/{index}/remove")
async def remove_skill_evidence(request: Request, skill_id: str, index: int, csrf_token: Annotated[str, Form()]):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    try:
        request.app.state.skills_bank.remove_evidence(skill_id, index)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Evidence not found") from exc
    return RedirectResponse(f"/skills/{skill_id}/evidence", status_code=303)


@router.get("/profile", response_class=HTMLResponse)
async def candidate_profile(request: Request):
    guard(request)
    return request.app.state.templates.TemplateResponse(
        request=request, name="profile.html",
        context=context(
            request,
            has_photo=request.app.state.profile_photo.exists(),
            interests=request.app.state.profile.interests,
        ),
    )


@router.post("/profile/interests/add")
async def add_interest(
    request: Request,
    name: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    category: Annotated[str, Form()] = "General",
    allowed_in_cv: Annotated[str | None, Form()] = None,
    enabled: Annotated[str | None, Form()] = None,
):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    name = name.strip()
    if not name:
        return RedirectResponse("/profile", status_code=303)
    interest_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or f"interest_{len(request.app.state.profile.interests) + 1}"
    profile = request.app.state.profile
    if not any(i.id == interest_id for i in profile.interests):
        new_interest = Interest(
            id=interest_id,
            name=name,
            category=category.strip() or "General",
            verified=True,
            allowed_in_cv=allowed_in_cv == "on" or allowed_in_cv is True,
            enabled=enabled == "on" or enabled is True,
        )
        updated_interests = [*profile.interests, new_interest]
        updated_profile = profile.model_copy(update={"interests": updated_interests})
        save_master_profile(updated_profile, request.app.state.settings)
        request.app.state.profile = updated_profile
        if hasattr(request.app.state, "skills_bank"):
            request.app.state.skills_bank.profile = updated_profile
            request.app.state.skills_bank.catalog = FactCatalog(updated_profile)
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/interests/{interest_id}/toggle")
async def toggle_interest(request: Request, interest_id: str, csrf_token: Annotated[str, Form()]):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    profile = request.app.state.profile
    updated_interests = []
    found = False
    for item in profile.interests:
        if item.id == interest_id:
            updated_interests.append(item.model_copy(update={"enabled": not item.enabled}))
            found = True
        else:
            updated_interests.append(item)
    if found:
        updated_profile = profile.model_copy(update={"interests": updated_interests})
        save_master_profile(updated_profile, request.app.state.settings)
        request.app.state.profile = updated_profile
        if hasattr(request.app.state, "skills_bank"):
            request.app.state.skills_bank.profile = updated_profile
            request.app.state.skills_bank.catalog = FactCatalog(updated_profile)
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/interests/{interest_id}/delete")
async def delete_interest(request: Request, interest_id: str, csrf_token: Annotated[str, Form()]):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    profile = request.app.state.profile
    updated_interests = [item for item in profile.interests if item.id != interest_id]
    if len(updated_interests) != len(profile.interests):
        updated_profile = profile.model_copy(update={"interests": updated_interests})
        save_master_profile(updated_profile, request.app.state.settings)
        request.app.state.profile = updated_profile
        if hasattr(request.app.state, "skills_bank"):
            request.app.state.skills_bank.profile = updated_profile
            request.app.state.skills_bank.catalog = FactCatalog(updated_profile)
    return RedirectResponse("/profile", status_code=303)


@router.get("/profile/photo/content")
async def profile_photo_content(request: Request):
    guard(request)
    if not request.app.state.profile_photo.exists():
        raise HTTPException(status_code=404, detail="Profile photo not found")
    return FileResponse(
        request.app.state.profile_photo.path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/profile/photo", response_class=HTMLResponse)
async def upload_profile_photo(
    request: Request,
    photo: Annotated[UploadFile, File()],
    csrf_token: Annotated[str, Form()],
    crop_x: Annotated[int, Form()] = 50,
    crop_y: Annotated[int, Form()] = 50,
):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    try:
        content = await photo.read(request.app.state.settings.profile_photo_max_bytes + 1)
        await cpu_work(request, request.app.state.profile_photo.save,
            photo.filename or "photo",
            photo.content_type or "",
            content,
            crop_x,
            crop_y,
        )
    except ProfilePhotoError as exc:
        return request.app.state.templates.TemplateResponse(
            request=request, name="profile.html",
            context=context(request, has_photo=request.app.state.profile_photo.exists(), error=str(exc)),
            status_code=422,
        )
    finally:
        await photo.close()
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/photo/remove")
async def remove_profile_photo(request: Request, csrf_token: Annotated[str, Form()]):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    request.app.state.profile_photo.remove()
    return RedirectResponse("/profile", status_code=303)


@router.get("/account/password", response_class=HTMLResponse)
async def password_form(request: Request):
    guard(request)
    return request.app.state.templates.TemplateResponse(request=request, name="password.html", context=context(request))


@router.post("/account/password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    repeat_password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
):
    guard(request)
    form = await request.form()
    if any(len(form.getlist(field)) != 1 for field in ("current_password", "new_password", "repeat_password", "csrf_token")):
        raise HTTPException(400, "Duplicate or missing authentication fields")
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    if new_password != repeat_password:
        return request.app.state.templates.TemplateResponse(
            request=request, name="password.html", context=context(request, error="The new passwords do not match."), status_code=422
        )
    try:
        if request.app.state.auth_slots.locked():
            raise HTTPException(429, "Authentication is busy. Try again shortly.")
        async with request.app.state.auth_slots:
            changed = await run_in_threadpool(request.app.state.auth_store.change_password, current_password, new_password)
    except ValueError as exc:
        return request.app.state.templates.TemplateResponse(
            request=request, name="password.html", context=context(request, error=str(exc)), status_code=422
        )
    if not changed:
        return request.app.state.templates.TemplateResponse(
            request=request, name="password.html", context=context(request, error="The current password is incorrect."), status_code=403
        )
    request.app.state.sessions.revoke(request.session.get("id", ""))
    request.session.clear()
    logger.info("Password changed", extra={"stage": "password_change"})
    return request.app.state.templates.TemplateResponse(request=request, name="password_changed.html", context=context(request))


@router.post('/preview/{slug}/summary/confirm')
async def confirm_saved_summary(request: Request, slug: str,
                                summary_confirmed: Annotated[str, Form()] = '', summary_token: Annotated[str, Form()] = ''):
    guard(request)
    try:
        _, resume, _, _ = request.app.state.storage.load_application(slug)
    except (OSError, ValidationError, ValueError) as exc:
        raise HTTPException(404, 'Resume not found') from exc
    review = summary_review(resume, request.app.state.profile, request.app.state.settings.csrf_secret,
        account_context(request.app.state.auth_store.username, 'saved', slug))
    require_confirmation(review, summary_confirmed, summary_token)
    request.app.state.storage.confirm_summary(slug, review['token'])
    return RedirectResponse(f'/preview/{slug}', status_code=303)


@router.get("/download/{slug}/{kind}")
async def download(request: Request, slug: str, kind: str):
    guard(request)
    filename = {"pdf": "resume.pdf", "docx": "resume.docx"}.get(kind)
    if not filename:
        raise HTTPException(status_code=404)
    try:
        path = request.app.state.storage.artifact(slug, filename)
        _, resume, _, metadata = request.app.state.storage.load_application(slug)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    review = summary_review(resume, request.app.state.profile, request.app.state.settings.csrf_secret,
        account_context(request.app.state.auth_store.username, 'saved', slug), metadata.get('summary_confirmation', ''))
    if review['required'] and 'text/html' in request.headers.get('accept', ''):
        return RedirectResponse(f'/preview/{slug}#summary-review', status_code=303)
    require_confirmation(review, '', '')
    media_type = (
        "application/pdf"
        if kind == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(path, media_type=media_type, filename=f"{slug}.{kind}")


@router.get("/health")
async def health(request: Request):
    return {"status": "ok"}


@router.get("/health/profile")
async def profile_health(request: Request):
    return {"status": "ok", **request.app.state.profile_status.public()}


@router.get("/health/skills")
async def skills_health(request: Request):
    return {"status": "ok", **request.app.state.skills_status.public()}


@router.get("/health/provider")
async def provider_health(request: Request):
    try:
        return await request.app.state.provider.health()
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/compare", response_class=HTMLResponse)
async def compare_view(
    request: Request,
    draft_id: str | None = None,
    task_id: str | None = None,
):
    guard(request)
    if task_id:
        task = request.app.state.task_manager.get_task(task_id)
        if task:
            if task.status == TaskStatus.COMPLETED and task.result:
                job = JobRequest.model_validate(task.result["job"])
                results = task.result["results"]
                return request.app.state.templates.TemplateResponse(
                    request=request, name="compare.html",
                    context=context(request, job=job, results=results, task_id=task_id, token_usage=task.token_usage),
                )
            if task.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                return request.app.state.templates.TemplateResponse(
                    request=request, name="task_progress.html",
                    context=context(request, task=task),
                )
            if task.status == TaskStatus.FAILED:
                return request.app.state.templates.TemplateResponse(
                    request=request, name="compare.html",
                    context=context(request, error=task.error, job=None, results=None),
                )

    job = None
    if draft_id:
        try:
            job, _ = request.app.state.storage.load_draft(draft_id)
        except Exception:
            job = None
    return request.app.state.templates.TemplateResponse(
        request=request, name="compare.html",
        context=context(request, draft_id=draft_id, job=job, results=None),
    )


@router.post("/compare")
async def run_compare(
    request: Request,
    company: Annotated[str, Form()],
    role: Annotated[str, Form()],
    job_description: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    job_url: Annotated[str, Form()] = "",
):
    guard(request)
    limit_request(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    if len(job_description) > request.app.state.settings.max_job_description_chars:
        raise HTTPException(status_code=413, detail="Job description is too long")
    try:
        job = JobRequest(company=company, role=role, job_url=job_url or None, job_description=job_description)
    except ValidationError:
        return request.app.state.templates.TemplateResponse(
            request=request, name="compare.html",
            context=context(request, error="Check form fields and provide a complete job description.", job=None, results=None),
            status_code=422,
        )

    # Idempotency check to prevent duplicate comparison runs
    key = compute_idempotency_key(
        "compare",
        company=company.strip(),
        role=role.strip(),
        job_description=job_description.strip(),
    )

    task = await run_in_threadpool(request.app.state.task_manager.find_active_by_idempotency_key, key)
    if not task:
        task = request.app.state.task_manager.create_task(
            kind=TaskKind.COMPARE,
            payload={"job": job.model_dump(mode="json")},
            idempotency_key=key,
        )

    accept = request.headers.get("accept", "")
    is_xhr = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if "application/json" in accept or is_xhr:
        return JSONResponse(
            status_code=202,
            content={
                "task_id": task.task_id,
                "status": task.status.value,
                "status_url": f"/tasks/{task.task_id}",
                "view_url": f"/tasks/{task.task_id}/view",
            },
        )

    response = request.app.state.templates.TemplateResponse(
        request=request, name="task_progress.html",
        context=context(request, task=task),
        status_code=202,
    )
    response.headers["Location"] = f"/tasks/{task.task_id}/view"
    response.headers["X-Task-ID"] = task.task_id
    return response


@router.get("/diagnostics", response_class=HTMLResponse)
async def diagnostics_view(request: Request):
    guard(request)
    runs = request.app.state.diagnostics.list_runs() if hasattr(request.app.state, "diagnostics") else []
    try:
        health_info = await request.app.state.provider.health()
    except Exception as exc:
        health_info = {"status": "error", "error": str(exc)}
    return request.app.state.templates.TemplateResponse(
        request=request, name="diagnostics.html",
        context=context(request, runs=runs, health=health_info),
    )


@router.post("/diagnostics/clear")
async def clear_diagnostics(request: Request, csrf_token: Annotated[str, Form()]):
    guard(request)
    validate_csrf(csrf_token, request.cookies.get(request.app.state.settings.csrf_cookie_name, ""), request.app.state.settings.csrf_secret)
    if hasattr(request.app.state, "diagnostics"):
        request.app.state.diagnostics.clear()
    return RedirectResponse("/diagnostics", status_code=303)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return request.app.state.templates.TemplateResponse(request=request, name="login.html", context=context(request))


@router.post("/login")
async def login(request: Request, username: Annotated[str, Form()], password: Annotated[str, Form()]):
    form = await request.form()
    if any(len(form.getlist(field)) != 1 for field in ("username", "password", "csrf_token")):
        raise HTTPException(400, "Duplicate or missing authentication fields")
    if len(username) > 150 or len(password) > 256:
        raise HTTPException(422, "Authentication fields are too long")
    if request.app.state.auth_slots.locked():
        raise HTTPException(429, "Authentication is busy. Try again shortly.")
    accounts = getattr(request.app.state, "accounts", {"owner": request.app})
    account, target = "owner", request.app
    for account_name, candidate in accounts.items():
        if secrets.compare_digest(username.encode(), candidate.state.auth_store.username.encode()):
            account, target = account_name, candidate
    async with request.app.state.auth_slots:
        credential = await run_in_threadpool(target.state.auth_store.verify_with_version, username, password)
    if credential is None:
        return request.app.state.templates.TemplateResponse(
            request=request, name="login.html", context=context(request, error="Invalid username or password."), status_code=401)
    for candidate in accounts.values():
        candidate.state.sessions.revoke(request.session.get("id", ""))
    token = target.state.sessions.create(credential)
    request.session.clear()
    request.session["id"] = token
    request.session["account"] = account
    request.session["csrf_token"] = new_csrf_token(target.state.settings.csrf_secret)
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    guard(request)
    request.app.state.sessions.revoke_all()
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.post("/settings/fallback")
async def set_fallback(request: Request, enabled: Annotated[str, Form()] = "off"):
    guard(request)
    request.app.state.provider.save_settings(enabled == "on")
    return RedirectResponse("/", status_code=303)


@router.post("/preview/{slug}/layout")
async def change_resume_layout(request: Request, slug: str,
                               template_name: Annotated[Literal["modern_sidebar", "ats_classic"], Form()]):
    guard(request)
    try:
        _, _, _, metadata = request.app.state.storage.load_application(slug)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Resume not found") from exc
    photo = metadata.get("modern_photo_enabled", metadata.get("photo_enabled", False))
    await cpu_work(request, _refresh_photo_artifacts, request, slug, photo_enabled=photo, template_name=template_name)
    return RedirectResponse(f"/preview/{slug}", status_code=303)
