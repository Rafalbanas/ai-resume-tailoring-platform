from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_var
from app.core.security import FixedWindowLimiter, new_csrf_token
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
from app.services.skills_bank import SkillsBank
from app.services.storage import Storage

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
    fallback = settings.llm_fallback_provider
    app.state.provider = ResilientAIProvider(
        providers=providers,
        default_primary=primary if primary in providers else "ollama",
        default_fallback=fallback if fallback in providers else ("gemini" if primary != "gemini" else "ollama"),
    )
    yield


app = FastAPI(title="AI Resume Tailoring Automation Platform", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", uuid4().hex)
    token = request_id_var.set(request_id)
    request.state.csrf_token = request.cookies.get("csrf_token") or new_csrf_token(get_settings().csrf_secret)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.set_cookie(
        "csrf_token",
        request.state.csrf_token,
        secure=get_settings().base_url.startswith("https://"),
        httponly=True,
        samesite="strict",
    )
    return response


app.include_router(router)
