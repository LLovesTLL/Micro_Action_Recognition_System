from pathlib import Path
from uuid import uuid4

from ..core.config import settings
from ..schemas.inference import HeatmapFrame, InferenceResponse, TemporalPoint
from .model_service import model_service
from .video_service import extract_frame_features, sample_video_frames
from .visualization_service import create_heatmap_overlay, save_frame_image


def run_inference_pipeline(video_path: Path) -> InferenceResponse:
    # --- 优先尝试远程推理 (VideoMambaPro on Linux) ---
    remote_result = model_service.predict_remote(video_path)
    
    if "error" not in remote_result:
        # 远程执行成功逻辑 (这里需要对接后端可视化的具体中间数据，先做 Top-1 替换)
        top_class = remote_result.get("top1", "unknown")
        top_conf = remote_result.get("confidence", 0.0)
        duration = remote_result.get("duration", 0.0)
        note = f"Inference completed by REMOTE Linux Server ({remote_result.get('status')})."
        
        # 为了展示曲线，仍保留本地时序抽样逻辑 (或让远程也返回曲线数据)
        samples, _ = sample_video_frames(video_path, max_points=50)
    else:
        # 远程不通，回退到本地占位逻辑
        samples, duration = sample_video_frames(video_path, max_points=50)
        note = f"Remote Inference Failed: {remote_result.get('error')}. Falling back to LOCAL mode."

    temporal_points: list[TemporalPoint] = []
    heatmaps: list[HeatmapFrame] = []

    for i, sample in enumerate(samples):
        feature_vec = extract_frame_features(sample.frame)
        probs = model_service.score_feature_vector(feature_vec)
        temporal_points.append(TemporalPoint(t=sample.timestamp_sec, probs=probs))

        if i % 8 == 0:
            uid = uuid4().hex[:10]
            frame_name = f"frame_{uid}.jpg"
            heatmap_name = f"heatmap_{uid}.jpg"
            frame_path = settings.output_dir / frame_name
            heatmap_path = settings.output_dir / heatmap_name

            save_frame_image(sample.frame, frame_path)
            create_heatmap_overlay(sample.frame, heatmap_path)
            heatmaps.append(
                HeatmapFrame(
                    t=sample.timestamp_sec,
                    frame_path=f"/api/v1/assets/{frame_name}",
                    heatmap_path=f"/api/v1/assets/{heatmap_name}",
                )
            )

    aggregate = {name: 0.0 for name in model_service.class_names}
    for p in temporal_points:
        for name, val in p.probs.items():
            aggregate[name] += val

    if temporal_points:
        for k in aggregate:
            aggregate[k] /= len(temporal_points)
        top_class = max(aggregate, key=aggregate.get)
        top_conf = aggregate[top_class]
    else:
        top_class = "unknown"
        top_conf = 0.0

    note = (
        "Checkpoint metadata loaded. Current scoring uses integration fallback features; "
        "replace with your trained model forward pass for production-level accuracy."
    )
    if not model_service.checkpoint_loaded:
        note = "Checkpoint not loaded. Running pure fallback integration pipeline."

    return InferenceResponse(
        filename=video_path.name,
        top_class=top_class,
        top_confidence=float(top_conf),
        duration_sec=float(duration),
        temporal_probs=temporal_points,
        heatmaps=heatmaps,
        backend_note=note,
    )
