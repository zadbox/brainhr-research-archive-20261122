"""
Brain RH API - Point d'entrée FastAPI.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from api.google_access_log import install_google_callback_access_log_filter
from api.request_security import validate_cookie_authenticated_mutation_origin
from api.routers import (
    admin_users,
    auth,
    company_cvs,
    crustdata,
    cvs,
    enterprise_cv_templates,
    enterprises,
    integrations,
    interview_appointments,
    interview_sheet,
    llm_settings,
    matching,
    offres,
    projects,
    realtime_interview,
    talent_pool,
)
from brainrh.database import DATABASE_URL, database_healthcheck, init_db
from brainrh.paths import PROJECT_ROOT
from brainrh.settings import (
    get_app_env,
    get_bind_host,
    get_bind_port,
    get_cors_allowed_origin_regex,
    get_cors_allowed_origins,
    get_database_backend,
    get_log_level,
    get_logs_dir,
    get_runtime_configuration_state,
    is_production,
    should_enable_outbox_worker,
    should_enable_turnover_worker,
    should_enable_api_docs,
    should_log_to_file,
    should_reload,
    validate_runtime_configuration,
)

load_dotenv(PROJECT_ROOT / ".env")


def configure_logging() -> logging.Logger:
    install_google_callback_access_log_filter()
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if should_log_to_file():
        logs_dir = get_logs_dir()
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            handlers.insert(0, logging.FileHandler(logs_dir / "api.log", mode="a", encoding="utf-8"))
        except OSError:
            pass

    logging.basicConfig(
        level=getattr(logging, get_log_level(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )
    return logging.getLogger(__name__)


logger = configure_logging()
API_VERSION = "1.0.0"


def _normalize_api_path(path: str) -> str:
    normalized = path
    while normalized.startswith("/api/v1/api/v1/"):
        normalized = normalized[len("/api/v1"):]
    if normalized == "/api/v1/api/v1":
        return "/api/v1"
    return normalized


def _health_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sanitize_database_health(db_state: dict[str, str]) -> dict[str, str]:
    sanitized = dict(db_state)
    if is_production():
        sanitized.pop("error", None)
    return sanitized


def _build_readiness_payload() -> tuple[int, dict[str, object]]:
    db_state = _sanitize_database_health(database_healthcheck())
    runtime_state = get_runtime_configuration_state()
    is_ready = db_state["status"] == "ok" and runtime_state["status"] == "ok"
    payload: dict[str, object] = {
        "status": "ok" if is_ready else "error",
        "service": "brainrh-api",
        "version": API_VERSION,
        "environment": get_app_env(),
        "checked_at": _health_timestamp(),
        "database": db_state,
        "runtime": runtime_state,
    }
    return (200 if is_ready else 503), payload


def _build_public_health_payload() -> dict[str, object]:
    db_state = _sanitize_database_health(database_healthcheck())
    runtime_state = get_runtime_configuration_state()
    is_ready = db_state["status"] == "ok" and runtime_state["status"] == "ok"
    return {
        "status": "ok" if is_ready else "error",
        "service": "brainrh-api",
        "version": API_VERSION,
        "environment": get_app_env(),
        "checked_at": _health_timestamp(),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    worker_task = None
    cal_video_worker_task = None

    generic_outbox_enabled = should_enable_outbox_worker()
    turnover_worker_enabled = should_enable_turnover_worker()
    if generic_outbox_enabled or turnover_worker_enabled:
        logger.info("Démarrage du worker d’intégrations...")
        from brainrh.worker.outbox_worker import outbox_worker_loop

        worker_task = asyncio.create_task(
            outbox_worker_loop(
                interval_seconds=15,
                process_generic=generic_outbox_enabled,
                process_turnover=turnover_worker_enabled,
            )
        )

    from brainrh.worker.cal_video_worker_orchestrator import (
        cal_video_worker_orchestrator_loop,
        should_enable_cal_video_worker_orchestrator,
    )

    if should_enable_cal_video_worker_orchestrator():
        logger.info("Démarrage de l'orchestrateur Cal Video worker...")
        cal_video_worker_task = asyncio.create_task(cal_video_worker_orchestrator_loop())

    yield

    if worker_task:
        logger.info("Arrêt du worker outbox...")
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
    if cal_video_worker_task:
        logger.info("Arrêt de l'orchestrateur Cal Video worker...")
        cal_video_worker_task.cancel()
        try:
            await cal_video_worker_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    validate_runtime_configuration()
    api_docs_enabled = should_enable_api_docs()

    logger.info("Démarrage de l'API Brain RH (%s)", get_app_env())
    logger.info("Backend DB: %s", get_database_backend(DATABASE_URL))

    if os.getenv("XAI_API_KEY"):
        logger.info("XAI_API_KEY détectée → Grok disponible pour le reranking")
    else:
        logger.warning("XAI_API_KEY non trouvée → Seul OpenAI sera disponible pour le reranking")

    app = FastAPI(
        title="Brain RH API",
        version=API_VERSION,
        description="""
API de matching intelligent CV/Offre avec analyse LLM.

**Fonctionnalités:**
- Parsing de CVs (PDF/DOCX) avec extraction LLM
- Enrichissement d'offres avec génération must-have/nice-have
- Matching avec filtrage, scoring et re-ranking LLM
- Streaming temps-réel (SSE) pour traitements longs
- Gestion de projets et entreprises
- Génération de fiches d'entretien structurées
- Export CSV/JSON des résultats

**Documentation interactive:** `/docs` (Swagger UI) ou `/redoc` (ReDoc)
        """,
        docs_url="/docs" if api_docs_enabled else None,
        redoc_url="/redoc" if api_docs_enabled else None,
        openapi_url="/openapi.json" if api_docs_enabled else None,
        lifespan=lifespan,
    )

    cors_origins = get_cors_allowed_origins()
    cors_origin_regex = get_cors_allowed_origin_regex()
    if cors_origins or cors_origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_origin_regex=cors_origin_regex,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def normalize_duplicate_api_prefix(request: Request, call_next):
        normalized_path = _normalize_api_path(request.scope.get("path", ""))
        if normalized_path != request.scope.get("path"):
            request.scope["path"] = normalized_path
            request.scope["raw_path"] = normalized_path.encode("utf-8")
        return await call_next(request)

    @app.middleware("http")
    async def enforce_cookie_mutation_origin(request: Request, call_next):
        try:
            validate_cookie_authenticated_mutation_origin(request, action_label="cette action")
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)
        return await call_next(request)

    app.include_router(cvs.router, prefix="/api/v1/cvs", tags=["CVs"])
    app.include_router(offres.router, prefix="/api/v1/offres", tags=["Offres"])
    app.include_router(matching.router, prefix="/api/v1/matching", tags=["Matching"])
    app.include_router(projects.router, prefix="/api/v1/projects", tags=["Projets"])
    app.include_router(talent_pool.router, prefix="/api/v1/talent-pool", tags=["Vivier"])
    app.include_router(enterprises.router, prefix="/api/v1/enterprises", tags=["Entreprises"])
    app.include_router(enterprise_cv_templates.router, prefix="/api/v1/enterprises", tags=["Enterprise CV Templates"])
    app.include_router(interview_sheet.router, prefix="/api/v1/interview-sheet", tags=["Fiches d'entretien"])
    app.include_router(company_cvs.router, prefix="/api/v1", tags=["Company CVs"])
    app.include_router(interview_appointments.router, prefix="/api/v1/interview-appointments", tags=["Interview Appointments"])
    app.include_router(realtime_interview.router, prefix="/api/v1/realtime-interviews", tags=["Realtime Interview"])
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(integrations.router, prefix="/api/v1/integrations", tags=["Intégrations"])
    app.include_router(admin_users.router, prefix="/api/v1", tags=["Administration"])
    app.include_router(llm_settings.router, prefix="/api/v1", tags=["Administration"])
    app.include_router(crustdata.router, prefix="/api/v1/crustdata", tags=["Crustdata"])

    @app.get("/")
    def root():
        return {
            "name": "Brain RH API",
            "version": API_VERSION,
            "environment": get_app_env(),
            "docs": "/docs" if api_docs_enabled else None,
            "openapi": "/openapi.json" if api_docs_enabled else None,
        }

    @app.get("/health/live")
    def health_live():
        return {
            "status": "ok",
            "service": "brainrh-api",
            "version": API_VERSION,
            "environment": get_app_env(),
            "checked_at": _health_timestamp(),
        }

    @app.get("/health/ready")
    def health_ready():
        status_code, payload = _build_readiness_payload()
        return JSONResponse(status_code=status_code, content=payload)

    @app.get("/health")
    def health():
        payload = _build_public_health_payload()
        return JSONResponse(status_code=200 if payload["status"] == "ok" else 503, content=payload)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if is_production() and exc.status_code >= 500:
            logger.error("HTTP %s on %s %s: %s", exc.status_code, request.method, request.url.path, exc.detail)
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "code": "INTERNAL_ERROR",
                    "message": "Erreur interne du serveur",
                },
                headers=exc.headers,
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        content = {
            "code": "INTERNAL_ERROR",
            "message": "Erreur interne du serveur",
        }
        if not is_production():
            content["details"] = {"error": str(exc)}
        return JSONResponse(status_code=500, content=content)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=get_bind_host(),
        port=get_bind_port(),
        reload=should_reload(),
        log_level=get_log_level().lower(),
    )
