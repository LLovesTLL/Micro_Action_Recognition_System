import requests
from pathlib import Path
from typing import Any
from urllib.parse import quote
import time
import json
import struct
import threading

import numpy as np

import websocket

from ..core.config import settings

# --- 远程推理微服务调用器 ---
class ModelService:
    """
    Local backend calls Remote Inference Engine (Mamba-based) via SSH Tunnel or HTTP.
    This keeps the local machine (Windows) light and uses the Remote (Linux) for GPU heavy tasks.
    """

    def __init__(self, checkpoint_path: Path) -> None:
        self.checkpoint_path = checkpoint_path
        self._session = requests.Session()
        self._ws_lock = threading.Lock()
        self._realtime_ws: websocket.WebSocket | None = None
        self.class_names = [
            "shaking body", "sitting straightly", "shrugging", "turning around", "rising up",
            "bowing head", "head up", "tilting head", "turning head", "nodding",
            "shaking head", "scratching arms", "playing objects", "putting hands together",
            "rubbing hands", "pointing oneself", "clenching fist", "stretching arms",
            "retracting arms", "waving", "spreading hands", "hands touching fingers",
            "other finger movements", "illustrative gestures", "shaking legs", "curling legs",
            "spread legs", "closing legs", "crossing legs", "stretching feet",
            "retracting feet", "tiptoe", "scratching or touching neck", "scratching or touching chest",
            "scratching or touching back", "scratching or touching shoulder", "arms akimbo",
            "crossing arms", "playing or tidying hair", "scratching or touching hindbrain",
            "scratching or touching forehead", "scratching or touching face", "rubbing eyes",
            "touching nose", "touching ears", "covering face", "covering mouth",
            "pushing glasses", "patting legs", "touching legs", "scratching legs", "scratching feet"
        ]
        # 远程服务器地址 (如果是 SSH 隧道，通常是 localhost:9000/9001)
        self.remote_base_url = str(getattr(settings, "remote_base_url", "http://localhost:9000"))
        self.remote_realtime_base_url = str(getattr(settings, "remote_realtime_base_url", "http://localhost:9001"))
        self.remote_url = f"{self.remote_base_url}/predict"
        self.remote_render_url = f"{self.remote_base_url}/render_expert_video"
        self.remote_health_url = f"{self.remote_base_url}/health"
        self.remote_realtime_health_url = f"{self.remote_realtime_base_url}/health"
        self.remote_realtime_predict_url = f"{self.remote_realtime_base_url}/realtime/predict-frame"
        self.remote_realtime_predict_raw_url = f"{self.remote_realtime_base_url}/realtime/predict-frame-raw"
        self.is_remote_connected = self._check_remote_health()
        # 兼容性属性，防止 pipeline_service.py 报错
        self.checkpoint_loaded = self.is_remote_connected 

    def _check_remote_health(self) -> bool:
        try:
            resp = self._session.get(self.remote_health_url, timeout=2.0)
            return resp.status_code == 200
        except:
            return False

    def predict_remote(self, video_file_path: Path) -> dict[str, Any]:
        """
        Send video to remote Linux server for VideoMambaPro inference.
        """
        if not self.is_remote_connected:
            # 重试健康检查
            if not self._check_remote_health():
                return {"error": "Remote Inference Engine not reachable. Check SSH Tunnel or server status."}

        return self._post_video_to_remote(self.remote_url, video_file_path, timeout=120.0)

    def render_expert_video_remote(self, video_file_path: Path) -> dict[str, Any]:
        """Send video to remote server and ask it to render expert-annotated video."""
        if not self.is_remote_connected:
            if not self._check_remote_health():
                return {"error": "Remote Inference Engine not reachable. Check SSH Tunnel or server status."}
        return self._post_video_to_remote(self.remote_render_url, video_file_path, timeout=300.0)

    def stream_remote_download(self, filename: str) -> requests.Response:
        safe_name = quote(filename)
        url = f"{self.remote_base_url}/download/{safe_name}"
        return self._session.get(url, timeout=300.0, stream=True)

    def check_realtime_health(self) -> dict[str, Any]:
        try:
            resp = self._session.get(self.remote_realtime_health_url, timeout=2.0)
            if resp.status_code != 200:
                return {
                    "reachable": False,
                    "status_code": resp.status_code,
                    "detail": resp.text,
                }
            data = resp.json() if resp.text else {}
            data["reachable"] = True
            return data
        except Exception as exc:
            return {
                "reachable": False,
                "error": str(exc),
            }

    def predict_realtime_frame_remote(
        self,
        frame_bytes: bytes,
        session_id: str,
        mode: str,
        ts_client_ms: int,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            prefer_ws = bool(getattr(settings, "remote_realtime_use_ws", True))
            if prefer_ws:
                ws_payload = self._predict_realtime_frame_ws(
                    frame_bytes=frame_bytes,
                    session_id=session_id,
                    mode=mode,
                    ts_client_ms=ts_client_ms,
                    timeout=timeout,
                )
                if ws_payload is not None:
                    ws_payload.setdefault("transport", "ws")
                    ws_payload.setdefault("timing", {})
                    if "roundtrip_ms" not in ws_payload["timing"]:
                        ws_payload["timing"]["roundtrip_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
                    return ws_payload

            prefer_raw = bool(getattr(settings, "remote_realtime_use_raw", True))

            response = None
            transport = "unknown"
            if prefer_raw:
                # Raw JPEG body, metadata via query params.
                response = self._session.post(
                    self.remote_realtime_predict_raw_url,
                    params={
                        "session_id": session_id,
                        "mode": mode,
                        "ts_client_ms": str(ts_client_ms),
                    },
                    data=frame_bytes,
                    headers={"Content-Type": "image/jpeg"},
                    timeout=timeout,
                )

                if response is not None:
                    transport = "http_raw"

                # Fallback to multipart when remote hasn't been upgraded.
                if response.status_code in (404, 405, 415):
                    response = None
                    transport = "unknown"

            if response is None:
                response = self._session.post(
                    self.remote_realtime_predict_url,
                    files={"frame": (f"{session_id}.jpg", frame_bytes, "image/jpeg")},
                    data={
                        "session_id": session_id,
                        "mode": mode,
                        "ts_client_ms": str(ts_client_ms),
                    },
                    timeout=timeout,
                )
                transport = "http_multipart"

            if response.status_code != 200:
                return {
                    "error": f"Remote Realtime Server Error: {response.status_code}",
                    "detail": response.text,
                }

            payload = response.json()
            payload.setdefault("transport", transport)
            payload.setdefault("timing", {})
            if "roundtrip_ms" not in payload["timing"]:
                payload["timing"]["roundtrip_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
            return payload
        except Exception as exc:
            return {"error": str(exc)}

    def _ws_connect(self, timeout: float) -> websocket.WebSocket:
        url = str(getattr(settings, "remote_realtime_ws_url", "ws://localhost:9002/ws/realtime"))
        ws = websocket.create_connection(url, timeout=timeout)
        ws.settimeout(timeout)
        return ws

    def _ws_close(self) -> None:
        ws = self._realtime_ws
        self._realtime_ws = None
        if ws is None:
            return
        try:
            ws.close()
        except Exception:
            pass

    def _predict_realtime_frame_ws(
        self,
        frame_bytes: bytes,
        session_id: str,
        mode: str,
        ts_client_ms: int,
        timeout: float,
    ) -> dict[str, Any] | None:
        """Try websocket realtime inference; return None to fallback to HTTP."""

        url = str(getattr(settings, "remote_realtime_ws_url", ""))
        if not url:
            return None

        header = {
            "session_id": session_id,
            "mode": mode,
            "ts_client_ms": int(ts_client_ms),
            "content_type": "image/jpeg",
        }
        header_bytes = json.dumps(header, ensure_ascii=False).encode("utf-8")
        message = struct.pack(">I", len(header_bytes)) + header_bytes + frame_bytes

        with self._ws_lock:
            try:
                if self._realtime_ws is None:
                    self._realtime_ws = self._ws_connect(timeout)

                assert self._realtime_ws is not None
                self._realtime_ws.send(message, opcode=websocket.ABNF.OPCODE_BINARY)
                resp = self._realtime_ws.recv()
                if isinstance(resp, (bytes, bytearray)):
                    resp = resp.decode("utf-8", errors="replace")
                if not isinstance(resp, str):
                    return {"error": "Remote WS returned non-text payload"}
                return json.loads(resp)
            except websocket.WebSocketException:
                self._ws_close()
                return None
            except Exception:
                self._ws_close()
                return None

    def _post_video_to_remote(self, url: str, video_file_path: Path, timeout: float) -> dict[str, Any]:
        try:
            with open(video_file_path, 'rb') as f:
                response = self._session.post(
                    url,
                    files={'file': (video_file_path.name, f, 'video/mp4')},
                    timeout=timeout,
                )

            if response.status_code == 200:
                return response.json()
            return {"error": f"Remote Server Error: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": str(e)}

    def score_feature_vector(self, feature_vec: np.ndarray) -> dict[str, float]:
        """
        DISABLED: Random fallback is now disabled to ensure strict real-model inference.
        Returns empty results if called directly, as we now strictly rely on predict_remote.
        """
        return {name: 0.0 for name in self.class_names}


model_service = ModelService(settings.checkpoint_path)
