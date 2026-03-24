from pathlib import Path
from uuid import uuid4

import numpy as np

from ..core.config import settings
from ..schemas.inference import AttentionHotspot, HeatmapFrame, InferenceResponse, TemporalPoint, TopKItem
from .model_service import model_service
from .video_service import sample_video_frames
from .visualization_service import create_attention_overlay, create_heatmap_overlay, save_frame_image


def run_inference_pipeline(video_path: Path) -> InferenceResponse:
    # --- 严格执行远程推理 (VideoMambaPro on Linux) ---
    import logging
    logger = logging.getLogger(__name__)
    
    remote_result = model_service.predict_remote(video_path)
    logger.info(f"Remote result from server: {remote_result}")
    
    if "error" in remote_result:
        raise Exception(f"Strict Inference Failed: {remote_result.get('error')}")

    # 兼容不同键名
    top_class = remote_result.get("prediction") or remote_result.get("top1") or "Unknown"
    top_conf = float(remote_result.get("confidence") or 0.0)

    probs = remote_result.get("probs")
    if probs is None:
        probs = remote_result.get("logits")
    if not isinstance(probs, list):
        probs = []

    class_names = model_service.class_names
    if len(probs) != len(class_names):
        # 尺寸不一致时避免索引越界，用最小长度裁剪。
        valid_len = min(len(probs), len(class_names))
        probs = probs[:valid_len]
        class_names = class_names[:valid_len]

    probs_by_name = {name: float(probs[idx]) for idx, name in enumerate(class_names)}
    num_classes = int(remote_result.get("num_classes") or len(probs) or len(class_names))

    temporal_source = remote_result.get("temporal_source")
    temporal_probs_remote = remote_result.get("temporal_probs")
    temporal_frame_indices = remote_result.get("temporal_frame_indices")
    video_fps_remote = remote_result.get("video_fps")
    
    # 打印调试信息到控制台
    print(f"DEBUG: Selected top_class='{top_class}', confidence={top_conf}")
    
    # 获取视频时长
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = frame_count / fps if fps > 0 else 0
    cap.release()

    total_time_ms = remote_result.get("total_time_ms")
    infer_time_ms = remote_result.get("inference_time_ms")
    note = f"Verified Inference by REMOTE Linux Server (Raw: {top_class})."
    if total_time_ms is not None and infer_time_ms is not None:
        note += f" total={float(total_time_ms):.2f}ms, infer={float(infer_time_ms):.2f}ms"
    
    num_frames = 16
    attention_matrix = remote_result.get("attention_matrix")
    if isinstance(attention_matrix, list) and attention_matrix:
        num_frames = len(attention_matrix)

    hotspots_raw = remote_result.get("attention_hotspots") if isinstance(remote_result.get("attention_hotspots"), list) else []
    hotspots: list[AttentionHotspot] = []
    hotspot_by_frame: dict[int, AttentionHotspot] = {}
    for item in hotspots_raw:
        try:
            hs = AttentionHotspot(
                frame_index=int(item.get("frame_index", -1)),
                x1=float(item.get("x1", 0.0)),
                y1=float(item.get("y1", 0.0)),
                x2=float(item.get("x2", 0.0)),
                y2=float(item.get("y2", 0.0)),
                score=float(item.get("score", 0.0)),
            )
            hotspots.append(hs)
            hotspot_by_frame[hs.frame_index] = hs
        except Exception:
            continue

    # 抽取帧用于页面可视化
    samples, _ = sample_video_frames(video_path, max_points=num_frames)

    temporal_points: list[TemporalPoint] = []
    heatmaps: list[HeatmapFrame] = []

    valid_temporal_probs = (
        isinstance(temporal_probs_remote, list)
        and len(temporal_probs_remote) > 0
        and all(isinstance(row, list) for row in temporal_probs_remote)
    )

    if valid_temporal_probs:
        frame_count = len(temporal_probs_remote)
        timestamps: list[float] = []

        valid_idx = (
            isinstance(temporal_frame_indices, list)
            and len(temporal_frame_indices) == frame_count
            and isinstance(video_fps_remote, (int, float))
            and float(video_fps_remote) > 1e-6
        )

        if valid_idx:
            fps_remote = float(video_fps_remote)
            timestamps = [float(int(idx) / fps_remote) for idx in temporal_frame_indices]
        elif frame_count > 1:
            timestamps = [float(i * (duration / (frame_count - 1))) for i in range(frame_count)]
        else:
            timestamps = [0.0]

        for i, row in enumerate(temporal_probs_remote):
            valid_len = min(len(row), len(class_names))
            point_probs = {
                class_names[idx]: float(row[idx])
                for idx in range(valid_len)
            }
            temporal_points.append(TemporalPoint(t=timestamps[i], probs=point_probs))
    else:
        for sample in samples:
            temporal_points.append(TemporalPoint(t=sample.timestamp_sec, probs=probs_by_name))

    for idx, sample in enumerate(samples):
        if len(heatmaps) < 4:
            uid = uuid4().hex[:10]
            frame_name = f"frame_{uid}.jpg"
            heatmap_name = f"heatmap_{uid}.jpg"
            save_frame_image(sample.frame, settings.output_dir / frame_name)

            if isinstance(attention_matrix, list) and idx < len(attention_matrix):
                try:
                    att2d = np.asarray(attention_matrix[idx], dtype=np.float32)
                    hotspot = hotspot_by_frame.get(idx)
                    create_attention_overlay(
                        sample.frame,
                        att2d,
                        settings.output_dir / heatmap_name,
                        hotspot=hotspot.model_dump() if hotspot else None,
                    )
                except Exception:
                    create_heatmap_overlay(sample.frame, settings.output_dir / heatmap_name)
            else:
                create_heatmap_overlay(sample.frame, settings.output_dir / heatmap_name)

            heatmaps.append(
                HeatmapFrame(
                    t=sample.timestamp_sec,
                    frame_path=f"/api/v1/assets/{frame_name}",
                    heatmap_path=f"/api/v1/assets/{heatmap_name}",
                    sample_index=idx,
                    hotspot=hotspot_by_frame.get(idx),
                )
            )

    topk_raw = remote_result.get("topk") if isinstance(remote_result.get("topk"), list) else []
    topk = [
        TopKItem(
            label_id=int(item.get("label_id", -1)),
            label=str(item.get("label", "unknown")),
            confidence=float(item.get("confidence", 0.0)),
        )
        for item in topk_raw
    ]

    return InferenceResponse(
        filename=video_path.name,
        top_class=top_class,
        top_confidence=top_conf,
        duration_sec=float(duration),
        temporal_probs=temporal_points,
        heatmaps=heatmaps,
        backend_note=note,
        topk=topk,
        attention_source=remote_result.get("attention_source"),
        attention_hook_layer=remote_result.get("attention_hook_layer"),
        attention_hook_mode=remote_result.get("attention_hook_mode"),
        attention_normalization_mode=remote_result.get("attention_normalization_mode"),
        attention_hotspot_threshold=remote_result.get("attention_hotspot_threshold"),
        attention_hotspots=hotspots,
        temporal_source=temporal_source,
        temporal_inference_time_ms=remote_result.get("temporal_inference_time_ms"),
        temporal_frame_indices=[int(i) for i in temporal_frame_indices] if isinstance(temporal_frame_indices, list) else [],
        num_classes=num_classes,
        remote_device=remote_result.get("device"),
        preprocess_time_ms=remote_result.get("preprocess_time_ms"),
        inference_time_ms=remote_result.get("inference_time_ms"),
        postprocess_time_ms=remote_result.get("postprocess_time_ms"),
        total_time_ms=remote_result.get("total_time_ms"),
    )
