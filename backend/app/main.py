from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.agent import router as agent_router
from app.api.routes.assets import router as assets_router
from app.api.routes.generation import router as generation_router
from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.plugins import router as plugins_router
from app.api.routes.projects import router as projects_router
from app.api.routes.scheduler import router as scheduler_router
from app.api.routes.sequences import router as sequences_router
from app.core.db import SessionLocal, init_db
from app.domain.generation import ensure_builtin_generation_models


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    with SessionLocal() as db:
        ensure_builtin_generation_models(db)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Mibu New API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix="/api")
    app.include_router(projects_router, prefix="/api")
    app.include_router(assets_router, prefix="/api")
    app.include_router(sequences_router, prefix="/api")
    app.include_router(jobs_router, prefix="/api")
    app.include_router(generation_router, prefix="/api")
    app.include_router(scheduler_router, prefix="/api")
    app.include_router(plugins_router, prefix="/api")
    app.include_router(agent_router, prefix="/api")
    return app


app = create_app()
