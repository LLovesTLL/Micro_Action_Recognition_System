from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..core.config import settings
from ..schemas.inference import InferenceResponse
from ..services.pipeline_service import run_inference_pipeline


router = APIRouter()


@router.post("/infer", response_model=InferenceResponse)
async def infer_video(file: UploadFile = File(...)) -> InferenceResponse:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".mp4", ".avi", ".mov", ".mkv"}:
        raise HTTPException(status_code=400, detail="Only mp4/avi/mov/mkv files are supported.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb}MB limit.")

    file_id = uuid4().hex
    target_path = settings.upload_dir / f"{file_id}{ext}"
    target_path.write_bytes(content)

    try:
        return run_inference_pipeline(target_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Inference failed: {exc}") from exc


@router.get("/assets/{filename}")
def get_asset(filename: str) -> FileResponse:
    target = settings.output_dir / filename
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Asset not found.")
    return FileResponse(target)
