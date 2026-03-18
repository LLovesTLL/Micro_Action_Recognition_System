from pathlib import Path

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


def save_frame_image(frame: np.ndarray, output_path: Path) -> None:
    cv2.imwrite(str(output_path), frame)
