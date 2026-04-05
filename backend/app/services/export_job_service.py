from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from ..core.config import settings
from .model_service import model_service


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ExportJobService:
    def __init__(self, max_workers: int = 2, store_path: Path | None = None) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="render-job")
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._store_path = store_path or (settings.output_dir / "render_jobs_history.json")
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self._store_path.exists():
            return
        try:
            payload = json.loads(self._store_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return
            jobs = payload.get("jobs")
            if not isinstance(jobs, dict):
                return
            clean: dict[str, dict[str, Any]] = {}
            for key, val in jobs.items():
                if isinstance(key, str) and isinstance(val, dict):
                    clean[key] = val
            self._jobs = clean
        except Exception:
            # Keep service available even if local history file is malformed.
            self._jobs = {}

    def _persist_locked(self) -> None:
        payload = {"jobs": self._jobs}
        tmp = self._store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._store_path)

    def create_job(self, video_path: Path, callback_url: str | None = None) -> dict[str, Any]:
        job_id = uuid4().hex
        payload = {
            "job_id": job_id,
            "status": "queued",
            "created_at": _utc_now_iso(),
            "started_at": None,
            "finished_at": None,
            "progress": 0.0,
            "class_label": None,
            "result": None,
            "error": None,
        }

        with self._lock:
            self._jobs[job_id] = payload
            self._persist_locked()

        self._executor.submit(self._run_job, job_id, video_path, callback_url)
        return payload

    def _set_job_fields(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(kwargs)
            self._persist_locked()

    def _run_job(self, job_id: str, video_path: Path, callback_url: str | None) -> None:
        self._set_job_fields(job_id, status="running", started_at=_utc_now_iso(), progress=0.1)
        callback_payload: dict[str, Any]

        try:
            remote_result = model_service.render_expert_video_remote(video_path)
            if "error" in remote_result:
                raise RuntimeError(f"Remote render failed: {remote_result.get('error')}")

            render_filename = str(remote_result.get("render_filename") or "").strip()
            if not render_filename:
                raise RuntimeError("Remote render missing render_filename")

            inference: dict[str, Any] = {}
            inference_obj = remote_result.get("inference")
            if isinstance(inference_obj, dict):
                inference = inference_obj
            class_label = (
                inference.get("prediction")
                or inference.get("top_class")
                or remote_result.get("prediction")
                or None
            )

            remote_result["local_download_url"] = f"/api/v1/remote-download/{render_filename}"
            callback_payload = {
                "status": "success",
                "job_id": job_id,
                "result": remote_result,
            }
            self._set_job_fields(
                job_id,
                status="success",
                finished_at=_utc_now_iso(),
                progress=1.0,
                class_label=class_label,
                result=remote_result,
                error=None,
            )
        except Exception as exc:
            callback_payload = {
                "status": "error",
                "job_id": job_id,
                "error": str(exc),
            }
            self._set_job_fields(
                job_id,
                status="error",
                finished_at=_utc_now_iso(),
                progress=1.0,
                class_label=None,
                error=str(exc),
            )
        finally:
            video_path.unlink(missing_ok=True)

        if callback_url:
            try:
                requests.post(callback_url, json=callback_payload, timeout=5.0)
            except Exception:
                pass

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list_jobs(self, *, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [dict(v) for v in self._jobs.values()]

        if status:
            jobs = [j for j in jobs if str(j.get("status")) == status]

        jobs.sort(key=lambda j: str(j.get("created_at") or ""), reverse=True)
        limit = max(1, min(200, int(limit)))
        return jobs[:limit]

    def delete_job(self, job_id: str, *, force: bool = False) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False

            status = str(job.get("status") or "")
            if not force and status in {"queued", "running"}:
                raise ValueError("cannot delete active job without force=true")

            self._jobs.pop(job_id, None)
            self._persist_locked()
            return True

    def clear_jobs(self, *, force: bool = False, status: str | None = None) -> int:
        with self._lock:
            remove_ids: list[str] = []
            for job_id, job in self._jobs.items():
                s = str(job.get("status") or "")
                if status and s != status:
                    continue
                if not force and s in {"queued", "running"}:
                    continue
                remove_ids.append(job_id)

            for job_id in remove_ids:
                self._jobs.pop(job_id, None)

            if remove_ids:
                self._persist_locked()

            return len(remove_ids)


export_job_service = ExportJobService(max_workers=2)
