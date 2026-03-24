from pathlib import Path
from typing import Any

import cv2
import numpy as np


def create_heatmap_overlay(frame: np.ndarray, output_path: Path) -> None:
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Pseudo-attention map for integration phase; replace with real CAM later.
    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=8, sigmaY=8)
    norm = cv2.normalize(blurred, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    heatmap = cv2.applyColorMap(norm, cv2.COLORMAP_JET)

    overlay = cv2.addWeighted(frame, 0.5, heatmap, 0.5, 0)
    cv2.imwrite(str(output_path), overlay)


def create_attention_overlay(
    frame: np.ndarray,
    attention_2d: np.ndarray,
    output_path: Path,
    hotspot: dict[str, Any] | None = None,
) -> None:
    h, w = frame.shape[:2]

    att = np.asarray(attention_2d, dtype=np.float32)
    if att.ndim != 2:
        raise ValueError("attention_2d must be a 2D array")

    att = np.nan_to_num(att, nan=0.0, posinf=1.0, neginf=0.0)
    att = cv2.resize(att, (w, h), interpolation=cv2.INTER_CUBIC)
    att = cv2.normalize(att, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    heatmap = cv2.applyColorMap(att, cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(frame, 0.55, heatmap, 0.45, 0)

    if hotspot:
        x1 = int(float(hotspot.get("x1", 0.0)) * (w - 1))
        y1 = int(float(hotspot.get("y1", 0.0)) * (h - 1))
        x2 = int(float(hotspot.get("x2", 0.0)) * (w - 1))
        y2 = int(float(hotspot.get("y2", 0.0)) * (h - 1))
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (30, 50, 240), 2)

    cv2.imwrite(str(output_path), overlay)


def save_frame_image(frame: np.ndarray, output_path: Path) -> None:
    cv2.imwrite(str(output_path), frame)
