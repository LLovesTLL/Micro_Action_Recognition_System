import requests
from pathlib import Path
from typing import Any

import numpy as np

from ..core.config import settings

# --- 远程推理微服务调用器 ---
class ModelService:
    """
    Local backend calls Remote Inference Engine (Mamba-based) via SSH Tunnel or HTTP.
    This keeps the local machine (Windows) light and uses the Remote (Linux) for GPU heavy tasks.
    """

    def __init__(self, checkpoint_path: Path) -> None:
        self.checkpoint_path = checkpoint_path
        self.class_names = settings.class_names.copy()
        # 远程服务器地址 (如果是 SSH 隧道，通常是 localhost:9000)
        self.remote_url = "http://localhost:9000/predict"
        self.remote_health_url = "http://localhost:9000/health"
        self.is_remote_connected = self._check_remote_health()

    def _check_remote_health(self) -> bool:
        try:
            resp = requests.get(self.remote_health_url, timeout=2.0)
            return resp.status_code == 200
        except:
            return False

    def predict_remote(self, video_file_path: Path) -> dict[str, Any]:
        """
        Send video to remote Linux server for VideoMambaPro inference.
        """
        if not self.is_remote_connected:
            # 重试健康检查
            if not self._check_remote_health():
                return {"error": "Remote Inference Engine not reachable. Check SSH Tunnel or server status."}

        try:
            with open(video_file_path, 'rb') as f:
                response = requests.post(
                    self.remote_url, 
                    files={'file': (video_file_path.name, f, 'video/mp4')},
                    timeout=30.0 # 视频推理可能较慢
                )
            
            if response.status_code == 200:
                result = response.json()
                return result
            else:
                return {"error": f"Remote Server Error: {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def score_feature_vector(self, feature_vec: np.ndarray) -> dict[str, float]:
        # [旧逻辑：本地 Fallback 保持不动，作为兜底]
        seed = 42
        rng = np.random.default_rng(seed)
        projection = rng.normal(size=(feature_vec.shape[0], len(self.class_names)))
        logits = feature_vec @ projection
        logits = logits - np.max(logits)
        exp = np.exp(logits)
        probs = exp / np.sum(exp)
        return {name: float(prob) for name, prob in zip(self.class_names, probs)}


model_service = ModelService(settings.checkpoint_path)
