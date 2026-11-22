"""
Brain RH API - Point d'entrée FastAPI
API REST pour matching CV/Offre avec LLM
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from api.routers import cvs, offres, matching, projects, enterprises

# Créer application FastAPI
app = FastAPI(
    title="Brain RH API",
    version="1.0.0",
    description="""
API de matching intelligent CV/Offre avec analyse LLM.

**Fonctionnalités:**
- Parsing de CVs (PDF/DOCX) avec extraction LLM
- Enrichissement d'offres avec génération must-have/nice-have
- Matching avec filtrage, scoring et re-ranking LLM
- Streaming temps-réel (SSE) pour traitements longs
- Gestion de projets et entreprises
- Export CSV/JSON des résultats

**Documentation interactive:** `/docs` (Swagger UI) ou `/redoc` (ReDoc)
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# CORS pour développement local
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # React (CRA)
        "http://localhost:5173",  # Vite
        "http://localhost:8501",  # Streamlit (pour coexistence)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclure les routers
app.include_router(cvs.router, prefix="/api/v1/cvs", tags=["CVs"])
app.include_router(offres.router, prefix="/api/v1/offres", tags=["Offres"])
app.include_router(matching.router, prefix="/api/v1/matching", tags=["Matching"])
app.include_router(projects.router, prefix="/api/v1/projects", tags=["Projets"])
app.include_router(enterprises.router, prefix="/api/v1/enterprises", tags=["Entreprises"])


@app.get("/")
def root():
    """Page d'accueil de l'API"""
    return {
        "name": "Brain RH API",
        "version": "1.0.0",
        "docs": "/docs",
        "openapi": "/openapi.json"
    }


@app.get("/health")
def health():
    """Endpoint de santé pour monitoring"""
    return {"status": "ok"}


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Handler global des exceptions non gérées"""
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "Erreur interne du serveur",
            "details": {"error": str(exc)}
        }
    )


if __name__ == "__main__":
    # Lancer le serveur en développement
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Auto-reload en développement
        log_level="info"
    )
