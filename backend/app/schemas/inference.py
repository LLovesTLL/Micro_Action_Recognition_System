from pydantic import BaseModel, Field


class TemporalPoint(BaseModel):
    t: float = Field(description="Timestamp (seconds)")
    probs: dict[str, float] = Field(description="Class probability distribution")


class HeatmapFrame(BaseModel):
    t: float
    frame_path: str
    heatmap_path: str


class InferenceResponse(BaseModel):
    filename: str
    top_class: str
    top_confidence: float
    duration_sec: float
    temporal_probs: list[TemporalPoint]
    heatmaps: list[HeatmapFrame]
    backend_note: str
