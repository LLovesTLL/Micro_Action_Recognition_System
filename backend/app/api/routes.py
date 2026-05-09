from pathlib import Path
from uuid import uuid4
from urllib.parse import unquote
from time import perf_counter

from pydantic import BaseModel
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from ..core.config import settings
from ..schemas.inference import InferenceResponse, RenderExpertResponse
from ..services.export_job_service import export_job_service
from ..services.model_service import model_service
from ..services.pipeline_service import run_inference_pipeline
from ..services.realtime_service import realtime_registry
from ..services.storage_service import cleanup_storage_dirs
from ..services.upload_session_service import UploadSessionService
from ..services.report_service import generate_pdf_report
from ..schemas.realtime import (
    RealtimeFrameResponse,
    RealtimeHotspot,
    RealtimeSessionResponse,
    RealtimeSessionStartRequest,
    RealtimeSessionStopRequest,
    RealtimeTiming,
    RealtimeTopKItem,
)


router = APIRouter()
upload_session_service = UploadSessionService(settings.upload_dir / "sessions")


class UploadSessionCreateRequest(BaseModel):
    filename: str
    total_size: int
    chunk_size: int
    total_chunks: int


class RenderJobCreateRequest(BaseModel):
    callback_url: str | None = None


def _normalize_mode(mode: str) -> str:
    m = (mode or "fast").strip().lower()
    if m not in {"fast", "full"}:
        raise HTTPException(status_code=400, detail="mode must be 'fast' or 'full'")
    return m


async def _stream_save_upload_file(file: UploadFile, target_path: Path, max_bytes: int) -> int:
    total = 0
    with open(target_path, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                out.close()
                target_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb}MB limit.")
            out.write(chunk)
    return total


@router.post("/infer", response_model=InferenceResponse)
async def infer_video(file: UploadFile = File(...)) -> InferenceResponse:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".mp4", ".avi", ".mov", ".mkv"}:
        raise HTTPException(status_code=400, detail="Only mp4/avi/mov/mkv files are supported.")

    max_bytes = settings.max_upload_mb * 1024 * 1024

    file_id = uuid4().hex
    target_path = settings.upload_dir / f"{file_id}{ext}"
    total = await _stream_save_upload_file(file, target_path, max_bytes)
    if total <= 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

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

    max_bytes = settings.max_upload_mb * 1024 * 1024

    file_id = uuid4().hex
    target_path = settings.upload_dir / f"{file_id}{ext}"
    total = await _stream_save_upload_file(file, target_path, max_bytes)
    if total <= 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

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


@router.post("/upload-sessions")
def create_upload_session(payload: UploadSessionCreateRequest) -> dict:
    try:
        return upload_session_service.create_session(
            filename=payload.filename,
            total_size=payload.total_size,
            chunk_size=payload.chunk_size,
            total_chunks=payload.total_chunks,
            max_upload_mb=500,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/upload-sessions/{session_id}")
def get_upload_session(session_id: str) -> dict:
    try:
        return upload_session_service.get_status(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Upload session not found") from exc


@router.put("/upload-sessions/{session_id}/chunks/{chunk_index}")
async def upload_session_chunk(session_id: str, chunk_index: int, chunk: UploadFile = File(...)) -> dict:
    try:
        return await upload_session_service.write_chunk(session_id, chunk_index, chunk)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Upload session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/upload-sessions/{session_id}/infer", response_model=InferenceResponse)
def infer_from_upload_session(session_id: str) -> InferenceResponse:
    try:
        assembled_path = upload_session_service.assemble_file(session_id)
        return run_inference_pipeline(assembled_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Upload session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Inference failed: {exc}") from exc
    finally:
        upload_session_service.delete_session(session_id)


@router.post("/upload-sessions/{session_id}/render-expert-async")
def render_expert_async_from_upload_session(session_id: str, payload: RenderJobCreateRequest) -> dict:
    try:
        src_status = upload_session_service.get_status(session_id)
        ext = Path(str(src_status.get("filename") or "")).suffix.lower() or ".mp4"
        local_id = uuid4().hex
        target_path = settings.upload_dir / f"async_render_{local_id}{ext}"
        upload_session_service.move_assembled_to(session_id, target_path)

        job = export_job_service.create_job(target_path, callback_url=payload.callback_url)
        return {
            "status": "accepted",
            "job_id": job["job_id"],
            "job_status": job["status"],
            "created_at": job["created_at"],
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Upload session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Create render job failed: {exc}") from exc
    finally:
        upload_session_service.delete_session(session_id)


@router.get("/render-jobs/{job_id}")
def get_render_job(job_id: str) -> dict:
    job = export_job_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")
    return job


@router.delete("/render-jobs/{job_id}")
def delete_render_job(job_id: str, force: bool = Query(default=False)) -> dict:
    try:
        ok = export_job_service.delete_job(job_id, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not ok:
        raise HTTPException(status_code=404, detail="Render job not found")

    return {
        "status": "success",
        "deleted": 1,
        "job_id": job_id,
    }


@router.get("/render-jobs")
def list_render_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    class_label: str | None = Query(default=None),
) -> dict:
    items = export_job_service.list_jobs(limit=200, status=status)
    if class_label:
        key = class_label.strip().lower()
        items = [i for i in items if key in str(i.get("class_label") or "").lower()]
    items = items[:limit]

    return {
        "status": "success",
        "items": items,
        "limit": limit,
    }


@router.delete("/render-jobs")
def clear_render_jobs(
    force: bool = Query(default=False),
    status: str | None = Query(default=None),
) -> dict:
    deleted = export_job_service.clear_jobs(force=force, status=status)
    return {
        "status": "success",
        "deleted": deleted,
        "force": force,
        "status_filter": status,
    }


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
    stats = cleanup_storage_dirs(settings.upload_dir)
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


@router.post('/export-report')
def export_report(payload: dict) -> FileResponse:
    try:
        # optional: payload may include 'source_video_path' referring to a server-side path
        source = None
        src = payload.get('source_video_path') if isinstance(payload, dict) else None
        if src:
            from pathlib import Path

            p = Path(str(src))
            if p.exists() and p.is_file():
                source = p

        pdf = generate_pdf_report(payload, source_video_path=source)
        return FileResponse(pdf, media_type='application/pdf', filename=pdf.name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Export report failed: {exc}") from exc


@router.get("/realtime/health")
def realtime_health() -> dict:
    return {
        "status": "ok",
        "local": {
            "service": "backend_realtime_bridge",
            "sessions": "in_memory",
        },
        "remote_realtime": model_service.check_realtime_health(),
    }


@router.post("/realtime/session/start", response_model=RealtimeSessionResponse)
def realtime_session_start(payload: RealtimeSessionStartRequest) -> RealtimeSessionResponse:
    mode = _normalize_mode(payload.mode)
    created = realtime_registry.create_session(mode=mode)
    return RealtimeSessionResponse(session_id=created["session_id"], mode=mode)


@router.post("/realtime/session/stop")
def realtime_session_stop(payload: RealtimeSessionStopRequest) -> dict:
    ok = realtime_registry.delete_session(payload.session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Realtime session not found")
    return {
        "status": "success",
        "session_id": payload.session_id,
    }


@router.post("/realtime/frame", response_model=RealtimeFrameResponse)
async def realtime_frame_infer(
    session_id: str = Form(...),
    mode: str = Form(...),
    ts_client_ms: int = Form(...),
    frame: UploadFile = File(...),
) -> RealtimeFrameResponse:
    mode_normalized = _normalize_mode(mode)
    session = realtime_registry.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Realtime session not found")

    if bool(session.get("inflight")):
        raise HTTPException(status_code=429, detail="Previous frame is still in-flight")

    ext = Path(frame.filename or "").suffix.lower()
    if ext and ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="Only jpg/jpeg/png/webp frame is supported")

    payload = await frame.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Frame is empty")

    if len(payload) > 3 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Frame exceeds 3MB limit")

    realtime_registry.mark_inflight(session_id, True)
    t0 = perf_counter()
    try:
        remote = model_service.predict_realtime_frame_remote(
            frame_bytes=payload,
            session_id=session_id,
            mode=mode_normalized,
            ts_client_ms=ts_client_ms,
            timeout=30.0,
        )
        if "error" in remote:
            raise HTTPException(status_code=502, detail=f"Remote realtime failed: {remote.get('error')}")

        realtime_registry.touch_frame(session_id)

        topk_raw = remote.get("topk") if isinstance(remote.get("topk"), list) else []
        topk = [
            RealtimeTopKItem(
                label_id=int(item.get("label_id", -1)),
                label=str(item.get("label", "unknown")),
                confidence=float(item.get("confidence", 0.0)),
            )
            for item in topk_raw
        ]

        timing_remote = remote.get("timing") if isinstance(remote.get("timing"), dict) else {}
        total_ms = (perf_counter() - t0) * 1000.0
        timing = RealtimeTiming(
            queue_ms=float(timing_remote.get("queue_ms", 0.0)),
            remote_infer_ms=float(timing_remote.get("remote_infer_ms", 0.0)),
            roundtrip_ms=float(timing_remote.get("roundtrip_ms", 0.0)),
            total_ms=float(timing_remote.get("total_ms", total_ms)),
        )

        return RealtimeFrameResponse(
            session_id=session_id,
            frame_id=str(remote.get("frame_id") or uuid4().hex[:12]),
            mode=mode_normalized,
            top_class=str(remote.get("top_class") or "unknown"),
            top_confidence=float(remote.get("top_confidence") or 0.0),
            topk=topk,
            hotspot=(
                RealtimeHotspot(
                    x1=float(remote["hotspot"].get("x1", 0.0)),
                    y1=float(remote["hotspot"].get("y1", 0.0)),
                    x2=float(remote["hotspot"].get("x2", 0.0)),
                    y2=float(remote["hotspot"].get("y2", 0.0)),
                    score=float(remote["hotspot"].get("score", 0.0)),
                    source=str(remote["hotspot"].get("source") or "motion_diff"),
                )
                if isinstance(remote.get("hotspot"), dict)
                else None
            ),
            warming_up=bool(remote.get("warming_up", False)),
            timing=timing,
            source=str(remote.get("source") or "remote_realtime_server"),
        )
    finally:
        realtime_registry.mark_inflight(session_id, False)
