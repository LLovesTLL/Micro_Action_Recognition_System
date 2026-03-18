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
        self.class_names = [
            "nodding", "shaking head", "bowing head", "raising forehead", "frowning",
            "raising eyebrows", "single eyebrow raising", "unilateral mouth stretching", "mouth corner down", "smiling",
            "tightening lips", "pouting", "opening mouth", "biting lips", "sticking out tongue",
            "licking lips", "blinking", "squinting", "gazing left", "gazing right",
            "wide-range eye scanning", "eye dodging", "blank stare", "nasal dilation", "nose wrinkling",
            "sniffing", "holding breath", "swallowing", "adam's apple sliding", "jaw clenching",
            "propping chin", "touching face", "scratching ear", "rubbing eyes", "touching neck",
            "covering mouth", "hair stroking", "shrugging", "adjusting posture", "small hand movements",
            "finger tapping", "deep breathing", "rapid breathing", "sighing", "sneering",
            "bitter smiling", "fake smiling", "facial stiffness", "facial muscle twitching", "sweating forehead",
            "facial flushing", "pale complexion"
        ]
        # 远程服务器地址 (如果是 SSH 隧道，通常是 localhost:9000)
        self.remote_url = "http://localhost:9000/predict"
        self.remote_health_url = "http://localhost:9000/health"
        self.is_remote_connected = self._check_remote_health()
        # 兼容性属性，防止 pipeline_service.py 报错
        self.checkpoint_loaded = self.is_remote_connected 

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
        """
        DISABLED: Random fallback is now disabled to ensure strict real-model inference.
        Returns empty results if called directly, as we now strictly rely on predict_remote.
        """
        return {name: 0.0 for name in self.class_names}


model_service = ModelService(settings.checkpoint_path)
