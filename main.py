"""
FastAPI application entry point.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from config import settings
from database.session import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: runs startup and shutdown logic."""
    from scheduler import setup_scheduler, job_full_pipeline
    import threading

    # Startup
    logger.info("Starting Prediction Market AI system...")
    init_db()
    logger.info("Database initialized.")

    # Start scheduler (background jobs: scan every 30min, pipeline every 2hr, review every 1hr)
    scheduler = setup_scheduler()
    scheduler.start()
    logger.info("Scheduler started.")

    # Run full pipeline immediately on startup (in background thread)
    def run_initial_pipeline():
        logger.info("Running initial pipeline on startup...")
        job_full_pipeline()

    thread = threading.Thread(target=run_initial_pipeline, daemon=True)
    thread.start()

    # Start real-time Polymarket WebSocket monitor
    from services.realtime_monitor import start_realtime_monitor
    await start_realtime_monitor()

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Shutting down Prediction Market AI system.")


app = FastAPI(
    title="Prediction Market AI",
    description=(
        "An AI-powered prediction market analysis system that scans markets, "
        "conducts research, generates probability predictions, and makes "
        "risk-adjusted position recommendations."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware – allow all origins for development; tighten for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
async def health_check():
    """Simple liveness check."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "log_level": settings.LOG_LEVEL,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.LOG_LEVEL.lower(),
    )
