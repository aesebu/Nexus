from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.core.database import Base, engine
from app import models  # noqa: F401
from app.api.routes import router


@asynccontextmanager
async def lifespan(_app: FastAPI):
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


@app.exception_handler(ValueError)
def value_error_handler(_request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})
