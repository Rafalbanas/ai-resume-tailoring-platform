import json
import logging
import re
import time
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import ValidationError

from app.core.security import require_basic_auth, validate_csrf
from app.models.job import JobExtraction, JobRequest, JobUrlRequest
from app.models.resume import TailoredResume
from app.models.skills import SkillEvidence, VerifiedSkill
from app.services.ai_provider import AIProviderError
from app.services.analysis_validator import AnalysisValidator
from app.services.fact_validator import FactValidator
from app.services.profile_photo import ProfilePhotoError
from app.services.resume_editor import apply_resume_edits

router = APIRouter()
logger = logging.getLogger(__name__)


def context(request: Request, **values):
    return {"request": request, "csrf_token": request.state.csrf_token, **values}


def guard(request: Request) -> None:
    require_basic_auth(request)


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
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(
        request.headers.get("X-CSRF-Token", ""),
        request.cookies.get("csrf_token", ""),
        request.app.state.settings.csrf_secret,
    )
    result = await request.app.state.job_extractor.extract(payload.url)
    if result.extraction_method == "manual_required":
        logger.info("Job URL requires manual input", extra={"stage": "job_extract"})
    else:
        logger.info("Job URL extracted", extra={"stage": "job_extract", "method": result.extraction_method})
    return result


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    guard(request)
    return request.app.state.templates.TemplateResponse("index.html", context(request))


@router.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    company: Annotated[str, Form()],
    role: Annotated[str, Form()],
    job_description: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    job_url: Annotated[str, Form()] = "",
):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(csrf_token, request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
    if len(job_description) > request.app.state.settings.max_job_description_chars:
        raise HTTPException(status_code=413, detail="Job description is too long")
    try:
        job = JobRequest(company=company, role=role, job_url=job_url or None, job_description=job_description)
    except ValidationError:
        return request.app.state.templates.TemplateResponse(
            "index.html",
            context(request, error="Check the form fields and paste a complete job description."),
            status_code=422,
        )
    started = time.perf_counter()
    try:
        response = await request.app.state.provider.tailor(job, request.app.state.profile)
        response.analysis = AnalysisValidator(request.app.state.profile, request.app.state.skills_bank).validate(
            response.analysis, f"{job.role}\n{job.job_description}"
        )
    except AIProviderError as exc:
        logger.warning(
            "AI provider failed", extra={"stage": "ai_provider", "provider": request.app.state.provider.name}
        )
        return request.app.state.templates.TemplateResponse(
            "index.html", context(request, error=str(exc)), status_code=502
        )
    except Exception:
        logger.exception("AI workflow failed", extra={"stage": "n8n_or_mock"})
        return request.app.state.templates.TemplateResponse(
            "index.html",
            context(request, error="The AI provider did not return a valid response. Try again."),
            status_code=502,
        )
    draft_id = request.app.state.storage.save_draft(job, response)
    logger.info("Job analyzed", extra={"stage": "analyze", "duration_ms": int((time.perf_counter() - started) * 1000)})
    return request.app.state.templates.TemplateResponse(
        "analysis.html", context(request, job=job, analysis=response.analysis, draft_id=draft_id)
    )


@router.post("/generate/{draft_id}")
async def generate(request: Request, draft_id: str, csrf_token: Annotated[str, Form()]):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(csrf_token, request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
    try:
        job, response = request.app.state.storage.load_draft(draft_id)
    except (FileNotFoundError, json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=404, detail="Draft not found") from exc
    started = time.perf_counter()
    result = FactValidator(request.app.state.profile, request.app.state.skills_bank).validate(response.resume, job)
    layout_guide = request.app.state.reference_library.layout_guide()
    fitted_resume, layout_warnings = request.app.state.pdf_generator.fit_resume(
        result.resume, request.app.state.profile, layout_guide
    )
    warnings = result.warnings + layout_warnings
    template_name = "modern_sidebar"
    photo_enabled = request.app.state.profile_photo.exists()
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
    )
    request.app.state.pdf_generator.generate(
        fitted_resume,
        request.app.state.profile,
        folder / "resume.pdf",
        layout_guide,
        template_name=template_name,
        photo_enabled=photo_enabled,
    )
    request.app.state.docx_generator(
        fitted_resume,
        request.app.state.profile,
        folder / "resume.docx",
        photo_path=request.app.state.profile_photo.path,
        photo_enabled=photo_enabled,
        template_name=template_name,
    )
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
    resume_html = request.app.state.pdf_generator.render_html(
        resume,
        request.app.state.profile,
        metadata.get("layout_guide"),
        template_name=metadata.get("template_name", "modern_sidebar"),
        photo_enabled=metadata.get("photo_enabled", request.app.state.profile_photo.exists()),
    )
    return request.app.state.templates.TemplateResponse(
        "resume_preview.html", context(request, slug=slug, metadata=metadata, resume_html=resume_html)
    )


@router.get("/edit/{slug}", response_class=HTMLResponse)
async def edit_resume(request: Request, slug: str):
    guard(request)
    try:
        _, resume, _, metadata = request.app.state.storage.load_application(slug)
    except (OSError, ValidationError, json.JSONDecodeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Resume not found") from exc
    return request.app.state.templates.TemplateResponse(
        "resume_edit.html",
        context(request, slug=slug, metadata=metadata, resume=resume),
    )


def _regenerate_artifacts(
    request: Request,
    slug: str,
    job: JobRequest,
    resume: TailoredResume,
    *,
    template_name: str = "modern_sidebar",
    photo_enabled: bool = False,
) -> list[str]:
    result = FactValidator(request.app.state.profile, request.app.state.skills_bank).validate(resume, job)
    layout_guide = request.app.state.reference_library.layout_guide()
    fitted_resume, layout_warnings = request.app.state.pdf_generator.fit_resume(
        result.resume, request.app.state.profile, layout_guide
    )
    warnings = result.warnings + layout_warnings
    photo_enabled = bool(
        photo_enabled and template_name == "modern_sidebar" and request.app.state.profile_photo.exists()
    )
    folder = request.app.state.storage.save_current_resume(
        slug,
        fitted_resume,
        warnings,
        template_name=template_name,
        photo_enabled=photo_enabled,
        truth_lock_warnings=result.warnings,
        layout_warnings=layout_warnings,
    )
    request.app.state.pdf_generator.generate(
        fitted_resume,
        request.app.state.profile,
        folder / "resume.pdf",
        layout_guide,
        template_name=template_name,
        photo_enabled=photo_enabled,
    )
    request.app.state.docx_generator(
        fitted_resume,
        request.app.state.profile,
        folder / "resume.docx",
        photo_path=request.app.state.profile_photo.path,
        photo_enabled=photo_enabled,
        template_name=template_name,
    )
    return warnings


@router.post("/edit/{slug}")
async def save_resume_edit(request: Request, slug: str):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    form = await request.form()
    validate_csrf(
        str(form.get("csrf_token", "")),
        request.cookies.get("csrf_token", ""),
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
            template_name = "modern_sidebar"
        photo_enabled = form.get("photo_enabled") == "on"
        _regenerate_artifacts(
            request,
            slug,
            job,
            edited,
            template_name=template_name,
            photo_enabled=photo_enabled,
        )
    except (OSError, json.JSONDecodeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Resume not found") from exc
    except ValidationError as exc:
        return request.app.state.templates.TemplateResponse(
            "resume_edit.html",
            context(
                request,
                slug=slug,
                metadata=metadata,
                resume=resume,
                error=f"The edited CV is invalid: {exc.errors()[0]['msg']}",
            ),
            status_code=422,
        )
    return RedirectResponse(f"/preview/{slug}", status_code=303)


@router.post("/reset/{slug}")
async def reset_resume(request: Request, slug: str, csrf_token: Annotated[str, Form()]):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(csrf_token, request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
    try:
        job, _, generated, metadata = request.app.state.storage.load_application(slug)
        _regenerate_artifacts(
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
        "history.html", context(request, rows=request.app.state.storage.history())
    )


@router.post("/history/{slug}/delete")
async def delete_history_item(request: Request, slug: str, csrf_token: Annotated[str, Form()]):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(csrf_token, request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
    try:
        request.app.state.storage.delete_application(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Generated CV not found") from exc
    return RedirectResponse("/history", status_code=303)


@router.post("/history/clear")
async def clear_history(request: Request, csrf_token: Annotated[str, Form()]):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(csrf_token, request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
    request.app.state.storage.clear_history()
    return RedirectResponse("/history", status_code=303)


@router.get("/references", response_class=HTMLResponse)
async def references(request: Request):
    guard(request)
    return request.app.state.templates.TemplateResponse(
        "references.html", context(request, references=request.app.state.reference_library.list())
    )


@router.post("/references/upload", response_class=HTMLResponse)
async def upload_references(
    request: Request,
    files: Annotated[list[UploadFile], File()],
    csrf_token: Annotated[str, Form()],
):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(csrf_token, request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
    errors = []
    for upload in files[:20]:
        try:
            content = await upload.read(request.app.state.settings.reference_cv_max_bytes + 1)
            request.app.state.reference_library.upload(upload.filename or "reference", content)
        except ValueError as exc:
            errors.append(f"{upload.filename}: {exc}")
        finally:
            await upload.close()
    if errors:
        return request.app.state.templates.TemplateResponse(
            "references.html",
            context(request, references=request.app.state.reference_library.list(), errors=errors),
            status_code=422,
        )
    return RedirectResponse("/references", status_code=303)


@router.post("/references/{reference_id}/remove")
async def remove_reference(request: Request, reference_id: str, csrf_token: Annotated[str, Form()]):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(csrf_token, request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
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
    return request.app.state.templates.TemplateResponse("skills.html", context(request, groups=groups))


@router.get("/skills/new", response_class=HTMLResponse)
async def new_skill(request: Request):
    guard(request)
    return request.app.state.templates.TemplateResponse(
        "skill_form.html", context(request, skill=None, evidence_options=_evidence_options(request))
    )


@router.get("/skills/{skill_id}/edit", response_class=HTMLResponse)
async def edit_skill(request: Request, skill_id: str):
    guard(request)
    skill = request.app.state.skills_bank.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return request.app.state.templates.TemplateResponse(
        "skill_form.html", context(request, skill=skill, evidence_options=_evidence_options(request))
    )


@router.post("/skills/save", response_class=HTMLResponse)
async def save_skill(request: Request):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    form = await request.form()
    validate_csrf(str(form.get("csrf_token", "")), request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
    existing_id = str(form.get("existing_id", "")).strip()
    existing = request.app.state.skills_bank.get(existing_id) if existing_id else None
    try:
        skill = _skill_from_form(form, existing)
        request.app.state.skills_bank.update(existing.id, skill) if existing else request.app.state.skills_bank.add(skill)
    except (ValueError, ValidationError, KeyError) as exc:
        return request.app.state.templates.TemplateResponse(
            "skill_form.html", context(request, skill=existing, evidence_options=_evidence_options(request), error=str(exc)),
            status_code=422,
        )
    return RedirectResponse("/skills", status_code=303)


@router.post("/skills/{skill_id}/toggle")
async def toggle_skill(request: Request, skill_id: str, csrf_token: Annotated[str, Form()]):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(csrf_token, request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
    try:
        request.app.state.skills_bank.toggle(skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc
    return RedirectResponse("/skills", status_code=303)


@router.post("/skills/{skill_id}/delete")
async def delete_skill(request: Request, skill_id: str, csrf_token: Annotated[str, Form()]):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(csrf_token, request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
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
        "skill_evidence.html", context(request, skill=skill, evidence_options=_evidence_options(request))
    )


@router.post("/skills/{skill_id}/evidence")
async def add_skill_evidence(request: Request, skill_id: str):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    form = await request.form()
    validate_csrf(str(form.get("csrf_token", "")), request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
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
            "skill_evidence.html", context(request, skill=skill, evidence_options=_evidence_options(request), error=str(exc)),
            status_code=422,
        )
    return RedirectResponse(f"/skills/{skill_id}/evidence", status_code=303)


@router.post("/skills/{skill_id}/evidence/{index}/remove")
async def remove_skill_evidence(request: Request, skill_id: str, index: int, csrf_token: Annotated[str, Form()]):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(csrf_token, request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
    try:
        request.app.state.skills_bank.remove_evidence(skill_id, index)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Evidence not found") from exc
    return RedirectResponse(f"/skills/{skill_id}/evidence", status_code=303)


@router.get("/profile", response_class=HTMLResponse)
async def candidate_profile(request: Request):
    guard(request)
    return request.app.state.templates.TemplateResponse(
        "profile.html", context(request, has_photo=request.app.state.profile_photo.exists())
    )


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
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(csrf_token, request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
    try:
        content = await photo.read(request.app.state.settings.profile_photo_max_bytes + 1)
        request.app.state.profile_photo.save(
            photo.filename or "photo",
            photo.content_type or "",
            content,
            crop_x,
            crop_y,
        )
    except ProfilePhotoError as exc:
        return request.app.state.templates.TemplateResponse(
            "profile.html",
            context(request, has_photo=request.app.state.profile_photo.exists(), error=str(exc)),
            status_code=422,
        )
    finally:
        await photo.close()
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/photo/remove")
async def remove_profile_photo(request: Request, csrf_token: Annotated[str, Form()]):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(csrf_token, request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
    request.app.state.profile_photo.remove()
    return RedirectResponse("/profile", status_code=303)


@router.get("/account/password", response_class=HTMLResponse)
async def password_form(request: Request):
    guard(request)
    return request.app.state.templates.TemplateResponse("password.html", context(request))


@router.post("/account/password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    repeat_password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
):
    guard(request)
    request.app.state.limiter.check(request.client.host if request.client else "unknown")
    validate_csrf(csrf_token, request.cookies.get("csrf_token", ""), request.app.state.settings.csrf_secret)
    if new_password != repeat_password:
        return request.app.state.templates.TemplateResponse(
            "password.html", context(request, error="The new passwords do not match."), status_code=422
        )
    try:
        changed = request.app.state.auth_store.change_password(current_password, new_password)
    except ValueError as exc:
        return request.app.state.templates.TemplateResponse(
            "password.html", context(request, error=str(exc)), status_code=422
        )
    if not changed:
        return request.app.state.templates.TemplateResponse(
            "password.html", context(request, error="The current password is incorrect."), status_code=403
        )
    logger.info("Password changed", extra={"stage": "password_change"})
    return request.app.state.templates.TemplateResponse("password_changed.html", context(request))


@router.get("/download/{slug}/{kind}")
async def download(request: Request, slug: str, kind: str):
    guard(request)
    filename = {"pdf": "resume.pdf", "docx": "resume.docx"}.get(kind)
    if not filename:
        raise HTTPException(status_code=404)
    try:
        path = request.app.state.storage.artifact(slug, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    media_type = (
        "application/pdf"
        if kind == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(path, media_type=media_type, filename=f"{slug}.{kind}")


@router.get("/health")
async def health(request: Request):
    return {
        "status": "ok",
        "profile": request.app.state.profile_status.public(),
        "skills": request.app.state.skills_status.public(),
    }


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
