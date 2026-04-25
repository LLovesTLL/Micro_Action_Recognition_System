import time
from threading import Lock
from uuid import uuid4


class RealtimeSessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        self._lock = Lock()

    def create_session(self, mode: str) -> dict:
        sid = uuid4().hex
        now = time.time()
        payload = {
            'session_id': sid,
            'mode': mode,
            'created_at': now,
            'updated_at': now,
            'inflight': False,
            'frame_count': 0,
        }
        with self._lock:
            self._sessions[sid] = payload
        return payload

    def get_session(self, session_id: str) -> dict | None:
        with self._lock:
            session = self._sessions.get(session_id)
            return dict(session) if session else None

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def mark_inflight(self, session_id: str, flag: bool) -> bool:
        with self._lock:
            s = self._sessions.get(session_id)
            if not s:
                return False
            s['inflight'] = flag
            s['updated_at'] = time.time()
            return True

    def touch_frame(self, session_id: str) -> bool:
        with self._lock:
            s = self._sessions.get(session_id)
            if not s:
                return False
            s['frame_count'] = int(s.get('frame_count', 0)) + 1
            s['updated_at'] = time.time()
            return True


realtime_registry = RealtimeSessionRegistry()
