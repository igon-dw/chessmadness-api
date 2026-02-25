from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

# CORS configuration for local development and UI integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # Alternative dev server
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
