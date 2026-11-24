from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import Base, engine, get_db
from app.core.config import settings
from app import models  # noqa: F401
from app.api.routes import router
from app.worker_monitoring import active_worker_count


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.environment != "production":
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="NEXUS",
    description="NEXUS Supreme AI Intelligence - MVP",
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
def readiness() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "detail": "database unavailable"},
        )
    return {"status": "ready"}


@app.get("/health/worker", response_model=None)
def worker_health(db: Session = Depends(get_db)) -> dict[str, str | int] | JSONResponse:
    try:
        active_workers = active_worker_count(db)
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "detail": "worker status unavailable"},
        )
    if active_workers == 0:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "active_workers": 0},
        )
    return {"status": "healthy", "active_workers": active_workers}


@app.exception_handler(ValueError)
def value_error_handler(_request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})
