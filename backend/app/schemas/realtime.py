from pydantic import BaseModel, Field


class RealtimeTopKItem(BaseModel):
    label_id: int
    label: str
    confidence: float


class RealtimeTiming(BaseModel):
    queue_ms: float = 0.0
    remote_infer_ms: float = 0.0
    roundtrip_ms: float = 0.0
    total_ms: float = 0.0


class RealtimeHotspot(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    source: str = 'motion_diff'


class RealtimeFrameResponse(BaseModel):
    status: str = Field(default='success')
    session_id: str
    frame_id: str
    mode: str
    top_class: str
    top_confidence: float
    topk: list[RealtimeTopKItem] = Field(default_factory=list)
    hotspot: RealtimeHotspot | None = None
    warming_up: bool = False
    timing: RealtimeTiming = Field(default_factory=RealtimeTiming)
    source: str = 'remote_realtime_server'


class RealtimeSessionStartRequest(BaseModel):
    mode: str = 'fast'


class RealtimeSessionResponse(BaseModel):
    status: str = Field(default='success')
    session_id: str
    mode: str


class RealtimeSessionStopRequest(BaseModel):
    session_id: str
