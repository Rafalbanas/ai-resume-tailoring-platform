import json
import logging
import time
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import ValidationError

from app.core.security import require_basic_auth, validate_csrf
from app.models.job import JobExtraction, JobRequest, JobUrlRequest
from app.models.resume import TailoredResume
from app.services.ai_provider import AIProviderError
from app.services.fact_validator import FactValidator

router = APIRouter()
logger = logging.getLogger(__name__)


def context(request: Request, **values):
    return {"request": request, "csrf_token": request.state.csrf_token, **values}


def guard(request: Request) -> None:
    require_basic_auth(request)


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
            "index.html", context(request, error="Check the form fields and paste a complete job description."), status_code=422
        )
    started = time.perf_counter()
    try:
        response = await request.app.state.provider.tailor(job, request.app.state.profile)
    except AIProviderError as exc:
        logger.warning("AI provider failed", extra={"stage": "ai_provider", "provider": request.app.state.provider.name})
        return request.app.state.templates.TemplateResponse(
            "index.html", context(request, error=str(exc)), status_code=502
        )
    except Exception:
        logger.exception("AI workflow failed", extra={"stage": "n8n_or_mock"})
        return request.app.state.templates.TemplateResponse(
            "index.html", context(request, error="The AI provider did not return a valid response. Try again."),
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
    result = FactValidator(request.app.state.profile).validate(response.resume, job)
    layout_guide = request.app.state.reference_library.layout_guide()
    fitted_resume, layout_warnings = request.app.state.pdf_generator.fit_resume(
        result.resume, request.app.state.profile, layout_guide
    )
    warnings = result.warnings + layout_warnings
    slug, folder = request.app.state.storage.save_application(
        job, response.analysis, fitted_resume, warnings, layout_guide
    )
    request.app.state.pdf_generator.generate(
        fitted_resume, request.app.state.profile, folder / "resume.pdf", layout_guide
    )
    request.app.state.docx_generator(fitted_resume, request.app.state.profile, folder / "resume.docx")
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
    folder = request.app.state.settings.data_dir / "generated" / slug
    try:
        resume = TailoredResume.model_validate_json((folder / "resume.json").read_text(encoding="utf-8"))
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="Resume not found") from exc
    resume_html = request.app.state.pdf_generator.render_html(
        resume, request.app.state.profile, metadata.get("layout_guide")
    )
    return request.app.state.templates.TemplateResponse(
        "resume_preview.html", context(request, slug=slug, metadata=metadata, resume_html=resume_html)
    )


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    guard(request)
    return request.app.state.templates.TemplateResponse(
        "history.html", context(request, rows=request.app.state.storage.history())
    )


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
    media_type = "application/pdf" if kind == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(path, media_type=media_type, filename=f"{slug}.{kind}")


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/health/provider")
async def provider_health(request: Request):
    try:
        return await request.app.state.provider.health()
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
