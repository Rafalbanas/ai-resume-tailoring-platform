import difflib
from pathlib import Path

from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.datastructures import UploadFile

from app.core.security import validate_csrf
from app.routes.web import context, cpu_work, guard, limit_request
from app.services.cv_editor import CVEditorStore, split_sections
from app.services.processing import decoded, encoded, process
from app.services.storage import safe_filename
from app.services.task_manager import TaskKind, compute_idempotency_key

router = APIRouter()


def store(request):
    return CVEditorStore(request.app.state.settings.data_dir)


async def form_data(request):
    guard(request)
    limit_request(request)
    form = await request.form()
    settings = request.app.state.settings
    validate_csrf(str(form.get("csrf_token", "")), request.cookies.get(settings.csrf_cookie_name, ""), settings.csrf_secret)
    return form


def load(request, identifier):
    try:
        return store(request).load(identifier)
    except (OSError, ValueError) as exc:
        raise HTTPException(404, "Custom CV not found") from exc


def redirect(request, identifier=""):
    return RedirectResponse(f"{request.scope.get('root_path', '')}/custom-cvs/{identifier}", status_code=303)


@router.get("/custom-cvs/")
async def library(request: Request):
    guard(request)
    return request.app.state.templates.TemplateResponse(request=request, name="custom_cv_library.html",
        context=context(request, documents=store(request).list()))


@router.post("/custom-cvs/import")
async def import_cv(request: Request):
    form = await form_data(request)
    try:
        text = str(form.get("pasted_cv", ""))
        upload = form.get("cv_file")
        if not text.strip() and isinstance(upload, UploadFile) and upload.filename:
            suffix = Path(upload.filename).suffix.casefold()
            if suffix not in {'.pdf', '.docx'}:
                raise ValueError("Choose a PDF or DOCX file, or paste the CV text.")
            maximum = request.app.state.settings.reference_cv_max_bytes
            content = await upload.read(maximum + 1)
            if len(content) > maximum:
                raise ValueError("The CV file is too large. Paste its text instead.")
            text = await cpu_work(request, process, 'reference', {'suffix': suffix, 'content': encoded(content)}, timeout=20)
        identifier = store(request).create(str(form.get("cv_name", "")) or "Imported CV", text)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if 'application/json' in request.headers.get('accept', ''):
        return JSONResponse({'view_url': f'/custom-cvs/{identifier}'}, status_code=202)
    return redirect(request, identifier)


@router.post("/preview/{slug}/ai-editor")
async def edit_generated_cv(request: Request, slug: str):
    await form_data(request)
    try:
        job, resume, _, metadata = request.app.state.storage.load_application(slug)
        markup = await cpu_work(request, request.app.state.pdf_generator.render_html, resume,
                                request.app.state.profile, template_name="ats_classic", photo_enabled=False)
        text = BeautifulSoup(markup, "html.parser").body.get_text("\n", strip=True)
        identifier = store(request).create(metadata.get("cv_name") or job.role, text)
    except OSError as exc:
        raise HTTPException(404, "Saved CV not found") from exc
    except ValueError as exc:
        raise HTTPException(422, "Could not open this CV in the text editor. Copy its text and use Paste Existing CV.") from exc
    return redirect(request, identifier)


@router.get("/custom-cvs/{identifier}")
async def editor(request: Request, identifier: str):
    guard(request)
    doc = load(request, identifier)
    current_sections = split_sections(doc["current"])
    pending = doc["pending"]
    diff = []
    if pending:
        # Structured tuples remain autoescaped in Jinja (never render untrusted HTML diffs).
        original_lines = doc["current"].splitlines(keepends=True)
        proposed_lines = pending["text"].splitlines(keepends=True)
        matcher = difflib.SequenceMatcher(None, original_lines, proposed_lines)
        for tag, a, b, c, d in matcher.get_opcodes():
            diff.append((tag, "".join(original_lines[a:b]), "".join(proposed_lines[c:d])))
    return request.app.state.templates.TemplateResponse(request=request, name="custom_cv_editor.html",
        context=context(request, document=doc, sections=current_sections, changes=diff))


@router.post("/custom-cvs/{identifier}/apply")
async def apply_changes(request: Request, identifier: str):
    form = await form_data(request)
    doc = load(request, identifier)
    instructions = str(form.get("instructions", "")).strip()
    selected = list(dict.fromkeys(str(v) for v in form.getlist("sections")))
    additions = str(form.get("confirmed_additions", "")).strip()
    try:
        revision = int(str(form.get("revision", "-1")))
        store(request)._check_revision(doc, revision)
        if doc["pending"]:
            raise ValueError("Accept or discard the current proposal first.")
        if not 3 <= len(instructions) <= 30_000 or len(additions) > 10_000:
            raise ValueError("Enter 3–30,000 characters of instructions; confirmed additions may use up to 10,000 characters.")
        if not selected or set(selected) - {s["id"] for s in split_sections(doc["current"])}:
            raise ValueError("Select at least one current CV section to edit.")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    payload = {"cv_id": identifier, "revision": revision, "instructions": instructions,
               "selected_sections": selected, "confirmed_additions": additions,
               "llm_provider": str(form.get("llm_provider", "auto"))}
    key = compute_idempotency_key("custom_edit", **payload)
    task = request.app.state.task_manager.find_active_by_idempotency_key(key)
    if not task:
        task = request.app.state.task_manager.create_task(TaskKind.CUSTOM_EDIT, payload, key)
    return RedirectResponse(f"{request.scope.get('root_path', '')}/tasks/{task.task_id}/view", status_code=303)


@router.post("/custom-cvs/{identifier}/{action}")
async def update_cv(request: Request, identifier: str, action: str):
    form = await form_data(request)
    load(request, identifier)
    try:
        if action == "duplicate":
            return redirect(request, store(request).duplicate(identifier))
        if action == "delete":
            store(request).delete(identifier)
            return redirect(request)
        store(request).update(identifier, int(str(form.get("revision", "-1"))), action,
                              text=str(form.get("text", "")), name=str(form.get("name", "")))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return redirect(request, identifier)


@router.get("/custom-cvs/{identifier}/export/{kind}")
async def export_cv(request: Request, identifier: str, kind: str, template: str = "ats_classic"):
    guard(request)
    doc = load(request, identifier)
    if kind not in {"pdf", "docx"} or template not in {"ats_classic", "modern_sidebar"}:
        raise HTTPException(422, "Choose PDF or DOCX and an existing CV template.")
    try:
        output = await cpu_work(request, process, "text_cv_export",
                                {"text": doc["current"], "kind": kind, "template": template})
    except ValueError as exc:
        raise HTTPException(422, "Export failed. Your CV was kept; try again or use the other format.") from exc
    mime = "application/pdf" if kind == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(decoded(output), media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{safe_filename(doc["name"])}.{kind}"'})
