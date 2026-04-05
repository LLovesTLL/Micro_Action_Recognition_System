from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4


ALLOWED_VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv"}


class UploadSessionService:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        return self.base_dir / session_id

    def _meta_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "meta.json"

    def _chunks_dir(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "chunks"

    def _chunk_path(self, session_id: str, chunk_index: int) -> Path:
        return self._chunks_dir(session_id) / f"{int(chunk_index):06d}.part"

    def _final_path(self, session_id: str, ext: str) -> Path:
        return self._session_dir(session_id) / f"final{ext}"

    def _load_meta(self, session_id: str) -> dict[str, Any]:
        meta_path = self._meta_path(session_id)
        if not meta_path.exists():
            raise FileNotFoundError("upload session not found")
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def _save_meta(self, session_id: str, meta: dict[str, Any]) -> None:
        self._meta_path(session_id).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def create_session(
        self,
        *,
        filename: str,
        total_size: int,
        chunk_size: int,
        total_chunks: int,
        max_upload_mb: int,
    ) -> dict[str, Any]:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_VIDEO_EXTS:
            raise ValueError("Only mp4/avi/mov/mkv files are supported.")
        if total_size <= 0:
            raise ValueError("total_size must be positive")

        max_bytes = int(max_upload_mb) * 1024 * 1024
        if total_size > max_bytes:
            raise ValueError(f"File exceeds {max_upload_mb}MB limit.")

        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if total_chunks <= 0:
            raise ValueError("total_chunks must be positive")

        expected_chunks = (total_size + chunk_size - 1) // chunk_size
        if total_chunks != expected_chunks:
            raise ValueError("total_chunks mismatch with total_size/chunk_size")

        session_id = uuid4().hex
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        self._chunks_dir(session_id).mkdir(parents=True, exist_ok=True)

        meta = {
            "session_id": session_id,
            "filename": filename,
            "ext": ext,
            "total_size": int(total_size),
            "chunk_size": int(chunk_size),
            "total_chunks": int(total_chunks),
        }
        self._save_meta(session_id, meta)
        return self.get_status(session_id)

    def get_status(self, session_id: str) -> dict[str, Any]:
        meta = self._load_meta(session_id)
        chunk_dir = self._chunks_dir(session_id)
        uploaded = []
        if chunk_dir.exists():
            for p in chunk_dir.glob("*.part"):
                try:
                    uploaded.append(int(p.stem))
                except ValueError:
                    continue
        uploaded.sort()
        uploaded_size = 0
        for idx in uploaded:
            cp = self._chunk_path(session_id, idx)
            if cp.exists():
                uploaded_size += cp.stat().st_size

        total_size = int(meta["total_size"])
        progress = 0.0 if total_size <= 0 else min(1.0, uploaded_size / total_size)

        return {
            "status": "success",
            **meta,
            "uploaded_chunks": uploaded,
            "uploaded_size": uploaded_size,
            "progress": progress,
            "is_complete": len(uploaded) == int(meta["total_chunks"]),
        }

    async def write_chunk(self, session_id: str, chunk_index: int, upload_file) -> dict[str, Any]:
        meta = self._load_meta(session_id)
        total_chunks = int(meta["total_chunks"])
        if chunk_index < 0 or chunk_index >= total_chunks:
            raise ValueError("chunk index out of range")

        chunk_path = self._chunk_path(session_id, chunk_index)
        chunk_path.parent.mkdir(parents=True, exist_ok=True)

        with open(chunk_path, "wb") as f:
            while True:
                data = await upload_file.read(1024 * 1024)
                if not data:
                    break
                f.write(data)

        return self.get_status(session_id)

    def assemble_file(self, session_id: str) -> Path:
        meta = self._load_meta(session_id)
        total_chunks = int(meta["total_chunks"])
        ext = str(meta["ext"])

        final_path = self._final_path(session_id, ext)
        with open(final_path, "wb") as out:
            for idx in range(total_chunks):
                cp = self._chunk_path(session_id, idx)
                if not cp.exists():
                    raise ValueError(f"missing chunk: {idx}")
                with open(cp, "rb") as src:
                    shutil.copyfileobj(src, out, length=1024 * 1024)

        expected_size = int(meta["total_size"])
        actual_size = final_path.stat().st_size
        if expected_size != actual_size:
            final_path.unlink(missing_ok=True)
            raise ValueError("assembled file size mismatch")

        return final_path

    def move_assembled_to(self, session_id: str, target_path: Path) -> Path:
        meta = self._load_meta(session_id)
        assembled = self._final_path(session_id, str(meta["ext"]))
        if not assembled.exists():
            assembled = self.assemble_file(session_id)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        assembled.replace(target_path)
        return target_path

    def delete_session(self, session_id: str) -> None:
        shutil.rmtree(self._session_dir(session_id), ignore_errors=True)


upload_session_service: UploadSessionService | None = None
