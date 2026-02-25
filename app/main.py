from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routers import games, import_, lines, review, skills, themes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    logger.info("chessmadness-api started")
    yield
    logger.info("chessmadness-api shutting down")


app = FastAPI(
    title="chessmadness-api",
    description="Backend API for Chess Repertoire Trainer",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(themes.router)
app.include_router(lines.router)
app.include_router(import_.router)
app.include_router(review.router)
app.include_router(skills.router)
app.include_router(games.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
