from pydantic import BaseModel, Field


class TemporalPoint(BaseModel):
    t: float = Field(description="Timestamp (seconds)")
    probs: dict[str, float] = Field(description="Class probability distribution")


class AttentionHotspot(BaseModel):
    frame_index: int
    x1: float
    y1: float
    x2: float
    y2: float
    score: float


class HeatmapFrame(BaseModel):
    t: float
    frame_path: str
    heatmap_path: str
    sample_index: int | None = None
    hotspot: AttentionHotspot | None = None


class TopKItem(BaseModel):
    label_id: int
    label: str
    confidence: float


class InferenceResponse(BaseModel):
    filename: str
    top_class: str
    top_confidence: float
    duration_sec: float
    temporal_probs: list[TemporalPoint]
    heatmaps: list[HeatmapFrame]
    backend_note: str
    topk: list[TopKItem] = Field(default_factory=list)
    attention_source: str | None = None
    attention_hook_layer: str | None = None
    attention_hook_mode: str | None = None
    attention_normalization_mode: str | None = None
    attention_hotspot_threshold: float | None = None
    attention_hotspots: list[AttentionHotspot] = Field(default_factory=list)
    temporal_source: str | None = None
    temporal_inference_time_ms: float | None = None
    temporal_frame_indices: list[int] = Field(default_factory=list)
    num_classes: int | None = None
    remote_device: str | None = None
    preprocess_time_ms: float | None = None
    inference_time_ms: float | None = None
    postprocess_time_ms: float | None = None
    total_time_ms: float | None = None


class RenderMeta(BaseModel):
    frames: int | None = None
    fps: float | None = None
    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None


class RenderExpertResponse(BaseModel):
    status: str
    render_id: str
    render_filename: str
    download_url: str
    local_download_url: str
    render_meta: RenderMeta
    inference: dict[str, object]
