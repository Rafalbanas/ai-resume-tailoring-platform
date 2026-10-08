from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_var
from app.core.security import FixedWindowLimiter, new_csrf_token
from app.models.candidate import CandidateProfile
from app.routes.web import router
from app.services.auth_store import AuthStore
from app.services.docx_generator import generate_docx
from app.services.job_extractors import JobExtractorService
from app.services.mock_provider import MockAIProvider
from app.services.n8n_provider import N8NGeminiProvider
from app.services.ollama_provider import OllamaProvider
from app.services.pdf_generator import PDFGenerator
from app.services.storage import Storage

BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    profile = CandidateProfile.model_validate_json(settings.master_profile_path.read_text(encoding="utf-8"))
    auth_store = AuthStore(settings.auth_file_path, settings.app_username, settings.app_password)
    auth_store.initialize()
    app.state.settings = settings
    app.state.profile = profile
    app.state.auth_store = auth_store
    app.state.storage = Storage(settings.data_dir)
    app.state.job_extractor = JobExtractorService(settings)
    app.state.templates = Jinja2Templates(directory=BASE_DIR / "templates")
    app.state.pdf_generator = PDFGenerator(BASE_DIR / "templates", BASE_DIR / "static")
    app.state.docx_generator = generate_docx
    app.state.limiter = FixedWindowLimiter(settings.rate_limit_per_minute)
    providers = {
        "mock": lambda: MockAIProvider(),
        "n8n": lambda: N8NGeminiProvider(settings),
        "ollama": lambda: OllamaProvider(settings),
    }
    app.state.provider = providers[settings.ai_provider]()
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
