from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class VideoSample:
    timestamp_sec: float
    frame: np.ndarray


def sample_video_frames(video_path: Path, max_points: int = 40) -> tuple[list[VideoSample], float]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError("Failed to open uploaded video.")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if frame_count > 0 else 0.0

    if frame_count <= 0:
        cap.release()
        return [], duration

    target_indices = np.linspace(0, frame_count - 1, min(max_points, frame_count), dtype=int)
    results: list[VideoSample] = []

    for idx in target_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        t = float(idx / fps)
        results.append(VideoSample(timestamp_sec=t, frame=frame))

    cap.release()
    return results, float(duration)


def extract_frame_features(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)

    mean_val = float(np.mean(resized))
    std_val = float(np.std(resized))
    edges = cv2.Canny(resized, 80, 180)
    edge_ratio = float(np.mean(edges > 0))

    quadrants = [
        resized[:32, :32],
        resized[:32, 32:],
        resized[32:, :32],
        resized[32:, 32:],
    ]
    quad_means = [float(np.mean(q)) for q in quadrants]

    return np.array([mean_val, std_val, edge_ratio, *quad_means], dtype=np.float32)
