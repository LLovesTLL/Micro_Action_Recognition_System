from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router as api_router
from .core.config import settings
from .services.storage_service import cleanup_storage_dirs


app = FastAPI(
    title="Micro Action Recognition API",
    version="0.1.0",
    description="Backend service for micro-action recognition and feature visualization.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
def cleanup_on_startup() -> None:
    cleanup_storage_dirs(settings.upload_dir)


@app.on_event("shutdown")
def cleanup_on_shutdown() -> None:
    cleanup_storage_dirs(settings.upload_dir)


app.include_router(api_router, prefix="/api/v1", tags=["inference"])
