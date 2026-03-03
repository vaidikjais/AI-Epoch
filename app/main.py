"""
Main Application - FastAPI Application Entrypoint and Configuration

Main FastAPI application entrypoint that initializes the database, configures
CORS middleware, and sets up API routes. Handles application startup events
and provides health check endpoints for monitoring.
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.controller.pipelines_controller import router as pipelines_router
from app.controller.articles_controller import router as articles_router
from app.controller.admin_controller import router as admin_router
from app.controller.scout_controller import router as scout_router
from app.controller.curator_controller import router as curator_router
from app.controller.extractor_controller import router as extractor_router
from app.controller.email_controller import router as email_router
from app.controller.email_group_controller import router as email_groups_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting up. DB migrations managed by Alembic.")
    yield

app = FastAPI(title="Agentic Newsletter MVP", lifespan=lifespan)

origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(pipelines_router)
app.include_router(articles_router)
app.include_router(admin_router)
app.include_router(scout_router)
app.include_router(curator_router)
app.include_router(extractor_router)
app.include_router(email_router)
app.include_router(email_groups_router)

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
