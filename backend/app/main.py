"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth import router as auth_router
from app.auth.routes import limiter
from app.health import router as health_router
from app.pipelines import router as pipelines_router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    logger.info("Application starting...")
    # Startup code here
    yield
    logger.info("Application shutting down...")
    # Shutdown code here


app = FastAPI(
    title="AI-Powered Workflow Automator",
    description="Zapier-like pipeline automation with LLM support",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: configure per environment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(health_router)
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(pipelines_router, tags=["pipelines"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "AI-Powered Workflow Automator API"}
