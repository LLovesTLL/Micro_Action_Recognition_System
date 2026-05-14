import cgi
import http.server
import json
import os
import socketserver
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass
from threading import Lock
from urllib.parse import parse_qs, urlparse
import asyncio
import struct
from typing import Any, cast

try:
    import websockets
except Exception:  # pragma: no cover
    websockets = None

import cv2
import numpy as np
import torch

# Environment settings.
PROJECT_ROOT = "/data/xcguo/Project/Micro_action"
sys.path.append(PROJECT_ROOT)
sys.path.append(os.path.join(PROJECT_ROOT, "mamba"))
sys.path.append(os.path.join(PROJECT_ROOT, "causal-conv1d"))
CHECKPOINT_PATH = "/data/xcguo/Project/Micro_action/exp/mySelf/Thirteenth/checkpoint-best.pth"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
PORT = 9001
WS_PORT = 9002
INPUT_SIZE = 224
NUM_FRAMES = 16
TOPK_RETURN = 5
MAX_SESSIONS = 64
SESSION_TTL_SEC = 180
FAST_INFER_EVERY_N = 1

# Rejection + smoothing settings for realtime false-positive suppression.
NO_ACTION_LABEL = "no obvious action"
NO_ACTION_CONFIDENCE = 0.0
REJECT_TOP1_CONF_THRESH = 0.52
REJECT_TOP1_TOP2_MARGIN_THRESH = 0.10
REJECT_MOTION_SCORE_THRESH = 0.05
REJECT_MIN_VOTES = 2
SMOOTH_WINDOW = 3
SMOOTH_MIN_COUNT = 2

CLASSES_52 = [
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
    "pushing glasses", "patting legs", "touching legs", "scratching legs", "scratching feet",
]

mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1, 1)
std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1, 1)

model: Any = None


@dataclass
class SessionState:
    mode: str
    frames: deque
    updated_at: float
    frame_count: int = 0
    last_result: dict | None = None
    pred_history: deque | None = None


class SessionManager:
    def __init__(self):
        self._lock = Lock()
        self._sessions: dict[str, SessionState] = {}

    def get_or_create(self, session_id: str, mode: str) -> SessionState:
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            state = self._sessions.get(session_id)
            if state is None:
                if len(self._sessions) >= MAX_SESSIONS:
                    self._evict_oldest_locked()
                state = SessionState(
                    mode=mode,
                    frames=deque(maxlen=NUM_FRAMES),
                    updated_at=now,
                    frame_count=0,
                    last_result=None,
                    pred_history=deque(maxlen=SMOOTH_WINDOW),
                )
                self._sessions[session_id] = state
            else:
                state.mode = mode
                state.updated_at = now
                if state.pred_history is None:
                    state.pred_history = deque(maxlen=SMOOTH_WINDOW)
            return state

    def stats(self) -> dict:
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            return {
                "active_sessions": len(self._sessions),
                "ttl_sec": SESSION_TTL_SEC,
                "max_sessions": MAX_SESSIONS,
            }

    def _cleanup_locked(self, now: float) -> None:
        stale = [sid for sid, s in self._sessions.items() if now - s.updated_at > SESSION_TTL_SEC]
        for sid in stale:
            self._sessions.pop(sid, None)

    def _evict_oldest_locked(self) -> None:
        if not self._sessions:
            return
        oldest_sid = min(self._sessions.keys(), key=lambda sid: self._sessions[sid].updated_at)
        self._sessions.pop(oldest_sid, None)


session_manager = SessionManager()


def _safe_label(label_id: int) -> str:
    if 0 <= label_id < len(CLASSES_52):
        return CLASSES_52[label_id]
    return f"unknown_{label_id}"


def _decode_frame(frame_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(frame_bytes, dtype=np.uint8)
    frame_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame_bgr is None:
        raise ValueError("invalid frame bytes")
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    frame_rgb = cv2.resize(frame_rgb, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_AREA)
    return frame_rgb


def _build_input_tensor(frames: list[np.ndarray]) -> torch.Tensor:
    if not frames:
        raise ValueError("empty frame buffer")

    if len(frames) < NUM_FRAMES:
        pad = [frames[-1]] * (NUM_FRAMES - len(frames))
        frames = frames + pad

    arr = np.stack(frames[-NUM_FRAMES:])
    t = torch.from_numpy(arr).float() / 255.0
    t = t.permute(3, 0, 1, 2).unsqueeze(0)
    t = (t - mean) / std
    return t.to(DEVICE)


def _extract_motion_hotspot(prev_frame_rgb: np.ndarray, curr_frame_rgb: np.ndarray) -> dict | None:
    prev_gray = cv2.cvtColor(prev_frame_rgb, cv2.COLOR_RGB2GRAY)
    curr_gray = cv2.cvtColor(curr_frame_rgb, cv2.COLOR_RGB2GRAY)

    diff = cv2.absdiff(curr_gray, prev_gray)
    diff = cv2.GaussianBlur(diff, (5, 5), 0)
    _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    best = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(best))
    h, w = curr_gray.shape
    if area < max(24.0, 0.002 * w * h):
        return None

    x, y, bw, bh = cv2.boundingRect(best)
    x1 = x / max(1, w - 1)
    y1 = y / max(1, h - 1)
    x2 = (x + bw - 1) / max(1, w - 1)
    y2 = (y + bh - 1) / max(1, h - 1)

    score = min(1.0, area / max(1.0, 0.08 * w * h))
    return {
        "x1": float(max(0.0, min(1.0, x1))),
        "y1": float(max(0.0, min(1.0, y1))),
        "x2": float(max(0.0, min(1.0, x2))),
        "y2": float(max(0.0, min(1.0, y2))),
        "score": float(score),
        "source": "motion_diff",
    }


def _infer_clip(input_tensor: torch.Tensor) -> dict:
    if DEVICE == "cuda":
        torch.cuda.synchronize()
    t0 = time.perf_counter()
    with torch.inference_mode():
        with torch.cuda.amp.autocast(enabled=(DEVICE == "cuda"), dtype=torch.float16):
            assert model is not None
            output = model(input_tensor)
        if torch.is_tensor(output):
            logits = output
        elif isinstance(output, (list, tuple)) and output and torch.is_tensor(output[0]):
            logits = output[0]
        else:
            raise ValueError("unsupported model output")

        if logits.dim() == 1:
            logits = logits.unsqueeze(0)
        probs = torch.nn.functional.softmax(logits, dim=1).squeeze(0)

        # NOTE: torch ops on CUDA are async; .item() forces sync.
        conf, pred = torch.max(probs, dim=0)
        topk_conf, topk_idx = torch.topk(probs, k=min(TOPK_RETURN, probs.numel()))

        pred_id = int(pred.item())
        confidence = float(conf.item())

        topk = [
            {
                "label_id": int(idx.item()),
                "label": _safe_label(int(idx.item())),
                "confidence": float(score.item()),
            }
            for score, idx in zip(topk_conf, topk_idx)
        ]

    if DEVICE == "cuda":
        torch.cuda.synchronize()
    infer_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "top_class": _safe_label(pred_id),
        "top_confidence": confidence,
        "topk": topk,
        "remote_infer_ms": round(infer_ms, 3),
    }


def _postprocess_prediction(state: SessionState, infer: dict, hotspot: dict | None) -> dict:
    top1_conf = float(infer.get("top_confidence", 0.0) or 0.0)
    topk = infer.get("topk") or []
    top2_conf = float(topk[1].get("confidence", 0.0) or 0.0) if len(topk) >= 2 else 0.0
    margin = top1_conf - top2_conf
    motion_score = float((hotspot or {}).get("score", 0.0) or 0.0)

    reject_votes = 0
    if top1_conf < REJECT_TOP1_CONF_THRESH:
        reject_votes += 1
    if margin < REJECT_TOP1_TOP2_MARGIN_THRESH:
        reject_votes += 1
    if motion_score < REJECT_MOTION_SCORE_THRESH:
        reject_votes += 1

    candidate_label = NO_ACTION_LABEL if reject_votes >= REJECT_MIN_VOTES else str(infer.get("top_class") or NO_ACTION_LABEL)

    if state.pred_history is None:
        state.pred_history = deque(maxlen=SMOOTH_WINDOW)
    state.pred_history.append(candidate_label)

    labels = list(state.pred_history)
    # Resolve most frequent label in short window to reduce frame-level jitter.
    best_label = candidate_label
    best_count = 0
    for label in labels:
        count = labels.count(label)
        if count > best_count:
            best_label = label
            best_count = count

    final_label = best_label if best_count >= SMOOTH_MIN_COUNT else candidate_label

    if final_label == NO_ACTION_LABEL:
        return {
            "top_class": NO_ACTION_LABEL,
            "top_confidence": NO_ACTION_CONFIDENCE,
            "topk": [],
            "hotspot": None,
        }

    final_conf = top1_conf
    for item in topk:
        if str(item.get("label")) == final_label:
            final_conf = float(item.get("confidence", top1_conf) or top1_conf)
            break

    return {
        "top_class": final_label,
        "top_confidence": final_conf,
        "topk": topk,
        "hotspot": hotspot,
    }


try:
    from videomambapro.models.videomambapro import videomambapro_m16_ssv2 as create_model  # type: ignore[import-not-found]

    model = create_model(num_classes=52, num_frames=NUM_FRAMES)
    checkpoint = torch.load(CHECKPOINT_PATH, map_location="cpu")
    state_dict = checkpoint["model"] if "model" in checkpoint else checkpoint
    msg = model.load_state_dict(state_dict, strict=True)
    model.to(DEVICE).eval()

    if DEVICE == "cuda":
        torch.backends.cudnn.benchmark = True
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

        # Warmup to reduce first-request latency spikes.
        with torch.inference_mode():
            dummy = torch.randn(1, 3, NUM_FRAMES, INPUT_SIZE, INPUT_SIZE, device=DEVICE)
            with torch.cuda.amp.autocast(dtype=torch.float16):
                _ = model(dummy)

    print(f">>> [RealtimeServer] model loaded: {msg}")
except Exception as exc:
    print(f">>> [RealtimeServer] model load failed: {exc}")
    sys.exit(1)


class RealtimeHandler(http.server.BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _normalize_mode(self, raw) -> str:
        mode = (raw or "fast").strip().lower()
        return mode if mode in ("fast", "full") else "fast"

    def do_GET(self):
        if self.path == "/health":
            stats = session_manager.stats()
            self._send_json({
                "status": "remote_realtime_alive",
                "device": DEVICE,
                "model_loaded": model is not None,
                "gpu_available": torch.cuda.is_available(),
                **stats,
            })
            return
        self._send_json({"status": "error", "message": "Not Found"}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        t_start = time.perf_counter()

        if path == "/realtime/predict-frame-raw":
            qs = parse_qs(parsed.query or "")
            session_id = (qs.get("session_id") or [""])[0]
            if not session_id:
                self._send_json({"status": "error", "message": "missing session_id"}, status=400)
                return
            mode = self._normalize_mode((qs.get("mode") or [None])[0])

            length = self.headers.get("Content-Length")
            if not length:
                self._send_json({"status": "error", "message": "missing Content-Length"}, status=411)
                return
            try:
                content_len = int(length)
            except ValueError:
                self._send_json({"status": "error", "message": "invalid Content-Length"}, status=400)
                return

            t_read0 = time.perf_counter()
            frame_bytes = self.rfile.read(content_len)
            read_ms = (time.perf_counter() - t_read0) * 1000.0
            if not frame_bytes:
                self._send_json({"status": "error", "message": "empty frame body"}, status=400)
                return

            try:
                t_dec0 = time.perf_counter()
                frame_rgb = _decode_frame(frame_bytes)
                decode_ms = (time.perf_counter() - t_dec0) * 1000.0
            except Exception as exc:
                self._send_json({"status": "error", "message": f"invalid frame: {exc}"}, status=400)
                return

            state = session_manager.get_or_create(session_id, mode)
            state.frames.append(frame_rgb)
            state.frame_count += 1
            t_hs0 = time.perf_counter()
            hotspot = _extract_motion_hotspot(state.frames[-2], state.frames[-1]) if len(state.frames) >= 2 else None
            hotspot_ms = (time.perf_counter() - t_hs0) * 1000.0
            warming_up = len(state.frames) < NUM_FRAMES

            infer = None
            use_cache = False
            build_input_ms = 0.0
            if mode == "fast" and state.last_result is not None and (state.frame_count % FAST_INFER_EVERY_N != 0):
                infer = dict(state.last_result)
                infer["remote_infer_ms"] = 0.0
                use_cache = True
            else:
                try:
                    t_in0 = time.perf_counter()
                    input_tensor = _build_input_tensor(list(state.frames))
                    build_input_ms = (time.perf_counter() - t_in0) * 1000.0
                    infer = _infer_clip(input_tensor)
                    state.last_result = dict(infer)
                except Exception as exc:
                    self._send_json({"status": "error", "message": f"inference failed: {exc}"}, status=500)
                    return

            t_pp0 = time.perf_counter()
            final_pred = _postprocess_prediction(state, infer, hotspot)
            postprocess_ms = (time.perf_counter() - t_pp0) * 1000.0

            payload = {
                "status": "success",
                "session_id": session_id,
                "frame_id": uuid.uuid4().hex[:12],
                "mode": mode,
                "top_class": final_pred["top_class"],
                "top_confidence": final_pred["top_confidence"],
                "topk": final_pred["topk"],
                "hotspot": final_pred["hotspot"],
                "warming_up": warming_up,
                "source": "remote_realtime_server",
                "cached": use_cache,
            }

            total_ms = (time.perf_counter() - t_start) * 1000.0
            infer_ms = float(infer.get("remote_infer_ms", 0.0) or 0.0)
            payload["timing"] = {
                "queue_ms": 0.0,
                "remote_infer_ms": infer_ms,
                "roundtrip_ms": round(total_ms, 3),
                "total_ms": round(total_ms, 3),
                "read_ms": round(read_ms, 3),
                "decode_ms": round(decode_ms, 3),
                "hotspot_ms": round(hotspot_ms, 3),
                "build_input_ms": round(build_input_ms, 3),
                "postprocess_ms": round(postprocess_ms, 3),
                "non_infer_ms": round(max(0.0, total_ms - infer_ms), 3),
            }
            self._send_json(payload)
            return

        if path == "/realtime/predict-frame":
            content_type = self.headers.get("content-type") or ""
            ctype, pdict = cgi.parse_header(content_type)
            if ctype != "multipart/form-data":
                self._send_json({"status": "error", "message": "Content-Type must be multipart/form-data"}, status=400)
                return

            try:
                pdict_any: dict[str, Any] = dict(pdict)
                pdict_any["boundary"] = bytes(str(pdict_any["boundary"]), "utf-8")
                fields = cgi.parse_multipart(cast(Any, self.rfile), cast(Any, pdict_any))
            except Exception as exc:
                self._send_json({"status": "error", "message": f"parse_multipart failed: {exc}"}, status=400)
                return

            frame_items = fields.get("frame")
            session_items = fields.get("session_id")
            mode_items = fields.get("mode")

            if not frame_items or not session_items:
                self._send_json({"status": "error", "message": "missing frame/session_id"}, status=400)
                return

            session_id = str(session_items[0], "utf-8") if isinstance(session_items[0], bytes) else str(session_items[0])
            mode = (
                str(mode_items[0], "utf-8")
                if (mode_items and isinstance(mode_items[0], bytes))
                else str(mode_items[0])
                if mode_items
                else "fast"
            )
            mode = self._normalize_mode(mode)

            try:
                frame_bytes = frame_items[0]
                t_dec0 = time.perf_counter()
                frame_rgb = _decode_frame(frame_bytes)
                decode_ms = (time.perf_counter() - t_dec0) * 1000.0
            except Exception as exc:
                self._send_json({"status": "error", "message": f"invalid frame: {exc}"}, status=400)
                return

            state = session_manager.get_or_create(session_id, mode)
            state.frames.append(frame_rgb)
            state.frame_count += 1
            t_hs0 = time.perf_counter()
            hotspot = _extract_motion_hotspot(state.frames[-2], state.frames[-1]) if len(state.frames) >= 2 else None
            hotspot_ms = (time.perf_counter() - t_hs0) * 1000.0
            warming_up = len(state.frames) < NUM_FRAMES

            infer = None
            use_cache = False
            build_input_ms = 0.0
            if mode == "fast" and state.last_result is not None and (state.frame_count % FAST_INFER_EVERY_N != 0):
                infer = dict(state.last_result)
                infer["remote_infer_ms"] = 0.0
                use_cache = True
            else:
                try:
                    t_in0 = time.perf_counter()
                    input_tensor = _build_input_tensor(list(state.frames))
                    build_input_ms = (time.perf_counter() - t_in0) * 1000.0
                    infer = _infer_clip(input_tensor)
                    state.last_result = dict(infer)
                except Exception as exc:
                    self._send_json({"status": "error", "message": f"inference failed: {exc}"}, status=500)
                    return

            total_ms = (time.perf_counter() - t_start) * 1000.0
            t_pp0 = time.perf_counter()
            final_pred = _postprocess_prediction(state, infer, hotspot)
            postprocess_ms = (time.perf_counter() - t_pp0) * 1000.0
            infer_ms = float(infer.get("remote_infer_ms", 0.0) or 0.0)
            payload = {
                "status": "success",
                "session_id": session_id,
                "frame_id": uuid.uuid4().hex[:12],
                "mode": mode,
                "top_class": final_pred["top_class"],
                "top_confidence": final_pred["top_confidence"],
                "topk": final_pred["topk"],
                "hotspot": final_pred["hotspot"],
                "warming_up": warming_up,
                "source": "remote_realtime_server",
                "cached": use_cache,
                "timing": {
                    "queue_ms": 0.0,
                    "remote_infer_ms": infer_ms,
                    "roundtrip_ms": round(total_ms, 3),
                    "total_ms": round(total_ms, 3),
                    "decode_ms": round(decode_ms, 3),
                    "hotspot_ms": round(hotspot_ms, 3),
                    "build_input_ms": round(build_input_ms, 3),
                    "postprocess_ms": round(postprocess_ms, 3),
                    "non_infer_ms": round(max(0.0, total_ms - infer_ms), 3),
                },
            }
            self._send_json(payload)
            return

        self._send_json({"status": "error", "message": "Not Found"}, status=404)
        return


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


async def _ws_realtime_handler(ws):
    """WebSocket protocol: binary message = [4-byte BE header_len][header_json][jpeg_bytes]."""

    while True:
        msg = await ws.recv()
        t_start = time.perf_counter()

        if not isinstance(msg, (bytes, bytearray)):
            await ws.send(json.dumps({"status": "error", "message": "binary message required"}, ensure_ascii=False))
            continue
        if len(msg) < 4:
            await ws.send(json.dumps({"status": "error", "message": "invalid message"}, ensure_ascii=False))
            continue

        header_len = struct.unpack(">I", msg[:4])[0]
        if header_len <= 0 or header_len > 64 * 1024 or len(msg) < 4 + header_len:
            await ws.send(json.dumps({"status": "error", "message": "invalid header length"}, ensure_ascii=False))
            continue

        header_raw = msg[4 : 4 + header_len]
        frame_bytes = msg[4 + header_len :]
        if not frame_bytes:
            await ws.send(json.dumps({"status": "error", "message": "empty frame"}, ensure_ascii=False))
            continue

        try:
            header = json.loads(header_raw.decode("utf-8"))
        except Exception as exc:
            await ws.send(json.dumps({"status": "error", "message": f"invalid header json: {exc}"}, ensure_ascii=False))
            continue

        session_id = str(header.get("session_id") or "")
        if not session_id:
            await ws.send(json.dumps({"status": "error", "message": "missing session_id"}, ensure_ascii=False))
            continue
        mode = str(header.get("mode") or "fast")
        mode = mode.lower().strip()
        if mode not in ("fast", "full"):
            mode = "fast"

        try:
            t_dec0 = time.perf_counter()
            frame_rgb = _decode_frame(frame_bytes)
            decode_ms = (time.perf_counter() - t_dec0) * 1000.0
        except Exception as exc:
            await ws.send(json.dumps({"status": "error", "message": f"invalid frame: {exc}"}, ensure_ascii=False))
            continue

        state = session_manager.get_or_create(session_id, mode)
        state.frames.append(frame_rgb)
        state.frame_count += 1
        t_hs0 = time.perf_counter()
        hotspot = _extract_motion_hotspot(state.frames[-2], state.frames[-1]) if len(state.frames) >= 2 else None
        hotspot_ms = (time.perf_counter() - t_hs0) * 1000.0
        warming_up = len(state.frames) < NUM_FRAMES

        infer = None
        use_cache = False
        build_input_ms = 0.0
        if mode == "fast" and state.last_result is not None and (state.frame_count % FAST_INFER_EVERY_N != 0):
            infer = dict(state.last_result)
            infer["remote_infer_ms"] = 0.0
            use_cache = True
        else:
            try:
                t_in0 = time.perf_counter()
                input_tensor = _build_input_tensor(list(state.frames))
                build_input_ms = (time.perf_counter() - t_in0) * 1000.0
                infer = _infer_clip(input_tensor)
                state.last_result = dict(infer)
            except Exception as exc:
                await ws.send(json.dumps({"status": "error", "message": f"inference failed: {exc}"}, ensure_ascii=False))
                continue

        t_pp0 = time.perf_counter()
        final_pred = _postprocess_prediction(state, infer, hotspot)
        postprocess_ms = (time.perf_counter() - t_pp0) * 1000.0
        total_ms = (time.perf_counter() - t_start) * 1000.0
        infer_ms = float(infer.get("remote_infer_ms", 0.0) or 0.0)
        payload = {
            "status": "success",
            "session_id": session_id,
            "frame_id": uuid.uuid4().hex[:12],
            "mode": mode,
            "top_class": final_pred["top_class"],
            "top_confidence": final_pred["top_confidence"],
            "topk": final_pred["topk"],
            "hotspot": final_pred["hotspot"],
            "warming_up": warming_up,
            "source": "remote_realtime_server",
            "cached": use_cache,
            "timing": {
                "queue_ms": 0.0,
                "remote_infer_ms": infer_ms,
                "roundtrip_ms": round(total_ms, 3),
                "total_ms": round(total_ms, 3),
                "decode_ms": round(decode_ms, 3),
                "hotspot_ms": round(hotspot_ms, 3),
                "build_input_ms": round(build_input_ms, 3),
                "postprocess_ms": round(postprocess_ms, 3),
                "non_infer_ms": round(max(0.0, total_ms - infer_ms), 3),
            },
        }
        await ws.send(json.dumps(payload, ensure_ascii=False))


async def _run_ws_server():
    if websockets is None:
        raise RuntimeError("websockets package is not installed")

    async with websockets.serve(_ws_realtime_handler, "0.0.0.0", WS_PORT, max_size=6 * 1024 * 1024):
        print(f"Starting Remote Realtime WebSocket Server on {WS_PORT}...")
        await asyncio.Future()


if __name__ == "__main__":
    # Start HTTP server (9001) for compatibility + health; optional WS server (9002) for low-latency streaming.
    if websockets is None:
        print(">>> [RealtimeServer] websockets not installed; WS endpoint disabled. Install with: pip install websockets")
        print(f"Starting Remote Realtime Inference Server on {PORT}...")
        with ThreadingTCPServer(("", PORT), RealtimeHandler) as httpd:
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\n>>> Realtime Server Stopped.")
    else:
        def _run_http():
            print(f"Starting Remote Realtime Inference Server on {PORT}...")
            with ThreadingTCPServer(("", PORT), RealtimeHandler) as httpd:
                httpd.serve_forever()

        import threading

        http_thread = threading.Thread(target=_run_http, daemon=True)
        http_thread.start()

        try:
            asyncio.run(_run_ws_server())
        except KeyboardInterrupt:
            print("\n>>> Realtime Server Stopped.")
