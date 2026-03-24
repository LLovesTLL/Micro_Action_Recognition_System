from pathlib import Path
from uuid import uuid4
from urllib.parse import unquote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from ..core.config import settings
from ..schemas.inference import InferenceResponse, RenderExpertResponse
from ..services.model_service import model_service
from ..services.pipeline_service import run_inference_pipeline
from ..services.storage_service import cleanup_storage_dirs


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
    finally:
        target_path.unlink(missing_ok=True)


@router.post("/render-expert", response_model=RenderExpertResponse)
async def render_expert_video(file: UploadFile = File(...)) -> RenderExpertResponse:
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
        remote_result = model_service.render_expert_video_remote(target_path)
        if "error" in remote_result:
            raise HTTPException(status_code=502, detail=f"Remote render failed: {remote_result.get('error')}")

        render_filename = str(remote_result.get("render_filename") or "").strip()
        if not render_filename:
            raise HTTPException(status_code=502, detail="Remote render missing render_filename")

        remote_result["local_download_url"] = f"/api/v1/remote-download/{render_filename}"
        return RenderExpertResponse(**remote_result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Render failed: {exc}") from exc
    finally:
        target_path.unlink(missing_ok=True)


@router.get("/remote-download/{filename}")
def download_remote_render(filename: str) -> StreamingResponse:
    safe_name = Path(unquote(filename)).name
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid filename")

    try:
        resp = model_service.stream_remote_download(safe_name)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Remote download failed: {exc}") from exc

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Remote file not available")

    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}"'
    }
    return StreamingResponse(resp.iter_content(chunk_size=1024 * 64), media_type="video/mp4", headers=headers)


@router.post("/cleanup-temp")
def cleanup_temp_files() -> dict[str, int | str]:
    stats = cleanup_storage_dirs(settings.upload_dir, settings.output_dir)
    return {
        "status": "ok",
        "deleted_files": stats["deleted_files"],
        "deleted_dirs": stats["deleted_dirs"],
    }


@router.get("/assets/{filename}")
def get_asset(filename: str) -> FileResponse:
    target = settings.output_dir / filename
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Asset not found.")
    return FileResponse(target)
