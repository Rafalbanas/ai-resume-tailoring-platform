from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_var
from app.core.security import FixedWindowLimiter, new_csrf_token, validate_csrf
from app.routes.web import router
from app.services.auth_store import AuthStore
from app.services.diagnostics import DiagnosticLogStore
from app.services.docx_generator import generate_docx
from app.services.gemini_provider import GeminiProvider
from app.services.job_extractors import JobExtractorService
from app.services.mock_provider import MockAIProvider
from app.services.n8n_provider import N8NGeminiProvider
from app.services.ollama_provider import OllamaProvider
from app.services.pdf_generator import PDFGenerator
from app.services.profile_loader import load_master_profile
from app.services.profile_photo import ProfilePhotoStore
from app.services.reference_cvs import ReferenceCVLibrary
from app.services.resilient_provider import ResilientAIProvider
from app.services.session_store import SessionStore
from app.services.skills_bank import SkillsBank
from app.services.storage import Storage
from app.services.task_manager import TaskManager

BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    profile, profile_status = load_master_profile(settings)
    auth_store = AuthStore(settings.auth_file_path, settings.app_username, settings.app_password)
    auth_store.initialize()
    app.state.settings = settings
    app.state.profile = profile
    app.state.profile_status = profile_status
    app.state.skills_bank = SkillsBank(settings.skills_path, profile, settings.profile_mode)
    app.state.skills_status = app.state.skills_bank.status
    app.state.auth_store = auth_store
    app.state.sessions = SessionStore(settings.data_dir / "sessions.sqlite3", settings.session_ttl_seconds)
    app.state.login_limiter = FixedWindowLimiter(5, 300)
    app.state.storage = Storage(settings.data_dir)
    app.state.reference_library = ReferenceCVLibrary(settings.reference_cvs_path, settings.reference_cv_max_bytes)
    app.state.reference_library.refresh()
    app.state.profile_photo = ProfilePhotoStore(settings.profile_photo_path, settings.profile_photo_max_bytes)
    app.state.job_extractor = JobExtractorService(settings)
    app.state.templates = Jinja2Templates(directory=BASE_DIR / "templates")
    app.state.pdf_generator = PDFGenerator(
        BASE_DIR / "templates", BASE_DIR / "static", settings.data_dir, app.state.profile_photo
    )
    app.state.docx_generator = generate_docx
    app.state.limiter = FixedWindowLimiter(settings.rate_limit_per_minute)
    app.state.diagnostics = DiagnosticLogStore(settings.data_dir)
    providers = {
        "mock": MockAIProvider(app.state.skills_bank),
        "ollama": OllamaProvider(
            settings, reference_library=app.state.reference_library, skills_bank=app.state.skills_bank
        ),
        "gemini": GeminiProvider(
            settings, reference_library=app.state.reference_library, skills_bank=app.state.skills_bank
        ),
    }
    if settings.n8n_webhook_url and settings.n8n_webhook_secret:
        providers["n8n"] = N8NGeminiProvider(settings, app.state.skills_bank)
    app.state.providers = providers
    primary = settings.active_llm_provider
    if primary == "auto":
        primary = "ollama"
    if primary not in providers:
        raise RuntimeError("The selected AI provider is not configured; check its required settings.")
    fallback = settings.llm_fallback_provider
    app.state.provider = ResilientAIProvider(
        providers=providers,
        default_primary=primary,
        default_fallback=fallback if fallback in providers or fallback in {"none", ""} else "none",
        operation_budget_seconds=settings.llm_operation_budget_seconds,
    )
    app.state.provider.settings_path = settings.data_dir / "ai_settings.json"
    app.state.provider.load_settings()
    task_manager = TaskManager(settings.data_dir, budget_seconds=settings.llm_operation_budget_seconds)
    await task_manager.recover_on_startup()
    task_manager.start_worker(app.state)
    app.state.task_manager = task_manager
    yield
    task_manager.stop_worker()


app = FastAPI(title="AI Resume Tailoring Automation Platform", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", uuid4().hex)
    token = request_id_var.set(request_id)
    request.state.csrf_token = request.cookies.get(get_settings().csrf_cookie_name) or new_csrf_token(get_settings().csrf_secret)
    try:
        path = request.url.path
        root_path = request.scope.get("root_path", "")
        if root_path and (path == root_path or path.startswith(root_path + "/")):
            path = path[len(root_path):] or "/"
        public = path in {"/login", "/health"} or path.startswith("/static/")
        credential = request.app.state.auth_store.credential_version if not public else ""
        request.state.authenticated = bool(not public and request.app.state.sessions.valid(
            request.session.get("id", ""), credential))
        if not public and not request.state.authenticated:
            response = (RedirectResponse("/login", status_code=303) if request.method == "GET"
                        and not path.startswith(("/api/", "/health/", "/download/"))
                        else JSONResponse({"detail": "Authentication required"}, status_code=401))
        else:
            try:
                if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                    submitted = request.headers.get("X-CSRF-Token", "")
                    if not submitted and "form" in request.headers.get("content-type", ""):
                        await request.body()
                        submitted = str((await request.form()).get("csrf_token", ""))
                    validate_csrf(submitted, request.cookies.get(get_settings().csrf_cookie_name, ""), get_settings().csrf_secret)
                response = await call_next(request)
            except HTTPException as exc:
                response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    finally:
        request_id_var.reset(token)
    location = response.headers.get("Location", "")
    root_path = request.scope.get("root_path", "")
    if root_path and location.startswith("/") and not location.startswith("//"):
        if location != root_path and not location.startswith(root_path + "/"):
            response.headers["Location"] = root_path + location
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        get_settings().csrf_cookie_name,
        request.state.csrf_token,
        path=get_settings().app_root_path or "/",
        secure=request.url.scheme == "https" or get_settings().base_url.startswith("https://"),
        httponly=True,
        samesite="strict",
    )
    return response


app.include_router(router)


class ConfiguredSessionMiddleware(SessionMiddleware):
    """Use Starlette's maintained cookie mechanism with opaque server-side sessions."""
    def __init__(self, app):
        settings = get_settings()
        options = dict(secret_key=settings.csrf_secret, session_cookie=settings.session_cookie_name, path=settings.app_root_path or "/",
                       max_age=settings.session_ttl_seconds, same_site="strict")
        super().__init__(app, https_only=settings.base_url.startswith("https://"), **options)
        self.https_sessions = SessionMiddleware(app, https_only=True, **options)

    async def __call__(self, scope, receive, send):
        if scope.get("scheme") == "https":
            await self.https_sessions(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)


app.add_middleware(ConfiguredSessionMiddleware)
