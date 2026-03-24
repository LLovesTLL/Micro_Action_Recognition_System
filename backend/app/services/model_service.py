import requests
from pathlib import Path
from typing import Any
from urllib.parse import quote

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
            "shaking body", "sitting straightly", "shrugging", "turning around", "rising up",
            "bowing head", "head up", "tilting head", "turning head", "nodding",
            "shaking head", "scratching arms", "playing objects", "putting hands together",
            "rubbing hands", "pointing oneself", "clenching fist", "stretching arms",
            "retracting arms", "waving", "spreading hands", "hands touching fingers",
            "other finger movements", "illustrative gestures", "shaking legs", "curling legs",
            "spread legs", "closing legs", "crossing legs", "stretching feet",
            "retracting feet", "tiptoe", "scratching or touching neck", "scratching or touching chest",
            "scratching or touching back", "scratching or touching shoulder", "arms akimbo",
            "crossing arms", "playing or tidying hair", "scratching or touching hindbrain",
            "scratching or touching forehead", "scratching or touching face", "rubbing eyes",
            "touching nose", "touching ears", "covering face", "covering mouth",
            "pushing glasses", "patting legs", "touching legs", "scratching legs", "scratching feet"
        ]
        # 远程服务器地址 (如果是 SSH 隧道，通常是 localhost:9000)
        self.remote_base_url = "http://localhost:9000"
        self.remote_url = f"{self.remote_base_url}/predict"
        self.remote_render_url = f"{self.remote_base_url}/render_expert_video"
        self.remote_health_url = f"{self.remote_base_url}/health"
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

        return self._post_video_to_remote(self.remote_url, video_file_path, timeout=120.0)

    def render_expert_video_remote(self, video_file_path: Path) -> dict[str, Any]:
        """Send video to remote server and ask it to render expert-annotated video."""
        if not self.is_remote_connected:
            if not self._check_remote_health():
                return {"error": "Remote Inference Engine not reachable. Check SSH Tunnel or server status."}
        return self._post_video_to_remote(self.remote_render_url, video_file_path, timeout=300.0)

    def stream_remote_download(self, filename: str) -> requests.Response:
        safe_name = quote(filename)
        url = f"{self.remote_base_url}/download/{safe_name}"
        return requests.get(url, timeout=300.0, stream=True)

    def _post_video_to_remote(self, url: str, video_file_path: Path, timeout: float) -> dict[str, Any]:
        try:
            with open(video_file_path, 'rb') as f:
                response = requests.post(
                    url,
                    files={'file': (video_file_path.name, f, 'video/mp4')},
                    timeout=timeout,
                )

            if response.status_code == 200:
                return response.json()
            return {"error": f"Remote Server Error: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": str(e)}

    def score_feature_vector(self, feature_vec: np.ndarray) -> dict[str, float]:
        """
        DISABLED: Random fallback is now disabled to ensure strict real-model inference.
        Returns empty results if called directly, as we now strictly rely on predict_remote.
        """
        return {name: 0.0 for name in self.class_names}


model_service = ModelService(settings.checkpoint_path)
