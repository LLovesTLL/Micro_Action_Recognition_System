from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from google import genai

from ..core.config import settings


PROMPT_TEXT = """
你是一名微表情分析专家。请基于面部微动作和肢体语言分析访谈视频，推断受试者的情绪状态。  
忽略服装、背景或外部线索。  

仅返回一个 JSON 对象，且不要输出任何多余文本或 Markdown。
键名必须严格为：emotion_label、confidence、summary、evidence。
字段要求如下（内容请使用中文）：
- emotion_label：字符串，简明的主要情绪标签
- confidence：0 到 1 之间的数字
- summary：字符串，1-2 句解释推理过程的说明
- evidence：由简短证据字符串组成的数组（2-4 项）
""".strip()

TOP1_NOTE_TEMPLATE = """
补充信息（可选参考）：我们的动作识别 Top-1 结果为 "{label}"，置信度 {confidence:.3f}。
如果该信息对情绪判断有帮助，请在 evidence 中明确提及该点；若无帮助，请忽略该信息。
""".strip()

MODEL_NAME = getattr(settings, "gemini_model", "gemini-2.5-flash")
TEMPERATURE = getattr(settings, "gemini_temperature", 0.4)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_api_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "").strip()


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n", "", cleaned)
        cleaned = cleaned.replace("```", "").strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _normalize_result(payload: dict[str, Any], raw_text: str) -> dict[str, Any]:
    def _as_str(value: Any, default: str = "unknown") -> str:
        text = str(value or "").strip()
        return text if text else default

    def _as_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _as_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return []

    def _pick(*keys: str) -> Any:
        for key in keys:
            if key in payload:
                return payload.get(key)
        return None

    return {
        "emotion_label": _as_str(_pick("emotion_label", "情绪标签", "主要情绪", "情绪")),
        "confidence": max(0.0, min(1.0, _as_float(_pick("confidence", "置信度")))),
        "summary": _as_str(_pick("summary", "分析摘要", "摘要", "说明"), ""),
        "evidence": _as_list(_pick("evidence", "关键证据", "证据")),
        "raw_text": raw_text,
    }


def _analyze_with_gemini(
    video_path: Path,
    top_class: str | None = None,
    top_confidence: float | None = None,
) -> dict[str, Any]:
    api_key = _load_api_key()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY environment variable")

    client = genai.Client(api_key=api_key)
    file_id: str | None = None

    try:
        upload = client.files.upload(file=str(video_path))
        file_id = upload.name

        start = time.time()
        while True:
            status = client.files.get(name=file_id).state
            if status == "ACTIVE":
                break
            if status == "FAILED":
                raise RuntimeError("Gemini file processing failed")
            if time.time() - start > 120:
                raise TimeoutError("Gemini file processing timeout")
            time.sleep(2)

        prompt = PROMPT_TEXT
        if top_class:
            confidence = float(top_confidence or 0.0)
            prompt = f"{prompt}\n\n{TOP1_NOTE_TEMPLATE.format(label=top_class, confidence=confidence)}"

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[upload, prompt],
            config={"temperature": TEMPERATURE},
        )
        text = response.text or ""
        parsed = _extract_json(text) or {}
        return _normalize_result(parsed, text)
    finally:
        if file_id:
            try:
                client.files.delete(name=file_id)
            except Exception:
                pass


class EmotionJobService:
    def __init__(self, max_workers: int = 2, store_path: Path | None = None) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="emotion-job")
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._store_path = store_path or (settings.output_dir / "emotion_jobs_history.json")
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self._store_path.exists():
            return
        try:
            payload = json.loads(self._store_path.read_text(encoding="utf-8"))
            jobs = payload.get("jobs") if isinstance(payload, dict) else None
            if isinstance(jobs, dict):
                self._jobs = {str(k): v for k, v in jobs.items() if isinstance(v, dict)}
        except Exception:
            self._jobs = {}

    def _persist_locked(self) -> None:
        payload = {"jobs": self._jobs}
        tmp = self._store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._store_path)

    def _set_job_fields(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id, {})
            job.update(kwargs)
            job["job_id"] = job_id
            self._jobs[job_id] = job
            self._persist_locked()

    def create_job(
        self,
        video_path: Path,
        top_class: str | None = None,
        top_confidence: float | None = None,
    ) -> dict[str, Any]:
        job_id = uuid4().hex
        payload = {
            "job_id": job_id,
            "video_name": video_path.name,
            "top_class": top_class,
            "top_confidence": top_confidence,
            "status": "queued",
            "created_at": _utc_now_iso(),
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
        }

        with self._lock:
            self._jobs[job_id] = payload
            self._persist_locked()

        self._executor.submit(self._run_job, job_id, video_path, top_class, top_confidence)
        return payload

    def _run_job(
        self,
        job_id: str,
        video_path: Path,
        top_class: str | None,
        top_confidence: float | None,
    ) -> None:
        self._set_job_fields(job_id, status="running", started_at=_utc_now_iso())
        try:
            result = _analyze_with_gemini(video_path, top_class, top_confidence)
            self._set_job_fields(
                job_id,
                status="success",
                finished_at=_utc_now_iso(),
                result=result,
                error=None,
            )
        except Exception as exc:
            self._set_job_fields(
                job_id,
                status="error",
                finished_at=_utc_now_iso(),
                error=str(exc),
            )
        finally:
            try:
                video_path.unlink(missing_ok=True)
            except Exception:
                pass

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if isinstance(job, dict) else None


emotion_job_service = EmotionJobService()
