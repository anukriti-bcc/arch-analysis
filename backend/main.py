from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.analyze import router as analyze_router
from api.routes.experiments import router as experiments_router
from analysis.policy.product import PolicyConfigError, attribution_enabled, policy_name_from_env
from storage import store

app = FastAPI(
    title="Architecture Analysis Engine",
    description=(
        "Repository -> Tree-sitter parsing -> dependencies -> architecture rules -> "
        "conformance findings, enriched with Git-history evidence and ADR intent, "
        "with selective LLM review. See README.md."
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
    """Liveness plus the storage backend in use ("memory" or "postgresql") and whether it answers, and the escalation policy ("gated" = M8, or "v1")."""
    try:
        policy = policy_name_from_env()
    except PolicyConfigError as exc:
        policy = f"invalid: {exc}"
    try:
        attribution = "on" if attribution_enabled() else "off"
    except PolicyConfigError as exc:
        attribution = f"invalid: {exc}"
    return {"status": "ok", "storage": store.describe(), "escalation_policy": policy, "attribution_check": attribution}
