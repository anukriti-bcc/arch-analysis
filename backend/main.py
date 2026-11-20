from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.analyze import router as analyze_router
from api.routes.experiments import router as experiments_router
from storage import store

app = FastAPI(
    title="Architecture Analysis Engine",
    description=(
        "Repository -> Tree-sitter parsing -> dependencies -> architecture rules -> "
        "conformance findings, enriched with Git-history evidence and ADR intent, "
        "with selective LLM review. See docs/PROGRESS.md for the roadmap."
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router)
app.include_router(experiments_router)


@app.get("/")
def root() -> dict:
    return {
        "name": "Architecture Analysis Engine",
        "milestone": "2-5",
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict:
    """Liveness plus the storage backend in use ("memory" or "postgresql") and whether it answers. Used by the Docker healthcheck."""
    return {"status": "ok", "storage": store.describe()}
