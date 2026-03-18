from pathlib import Path
from typing import Any

import numpy as np

from ..core.config import settings

try:
    import torch
except Exception:  # pragma: no cover
    torch = None


class ModelService:
    """
    Current repository only has checkpoint weights, so this service loads metadata
    and provides a deterministic fallback classifier for end-to-end integration.
    """

    def __init__(self, checkpoint_path: Path) -> None:
        self.checkpoint_path = checkpoint_path
        self.class_names = settings.class_names.copy()
        self.checkpoint_loaded = False
        self.checkpoint_info: dict[str, Any] = {}
        self._load_checkpoint_metadata()

    def _load_checkpoint_metadata(self) -> None:
        if torch is None or not self.checkpoint_path.exists():
            return

        try:
            data = torch.load(self.checkpoint_path, map_location="cpu")
            self.checkpoint_loaded = True
            self.checkpoint_info = {"type": type(data).__name__}

            if isinstance(data, dict):
                for key in ["class_names", "labels", "classes"]:
                    names = data.get(key)
                    if isinstance(names, (list, tuple)) and all(isinstance(x, str) for x in names):
                        self.class_names = list(names)
                        break
        except Exception as exc:
            self.checkpoint_info = {"error": str(exc)}

    def score_feature_vector(self, feature_vec: np.ndarray) -> dict[str, float]:
        # Fixed projection matrix keeps output deterministic for demo and API integration.
        seed = 42
        rng = np.random.default_rng(seed)
        projection = rng.normal(size=(feature_vec.shape[0], len(self.class_names)))
        logits = feature_vec @ projection
        logits = logits - np.max(logits)
        exp = np.exp(logits)
        probs = exp / np.sum(exp)
        return {name: float(prob) for name, prob in zip(self.class_names, probs)}


model_service = ModelService(settings.checkpoint_path)
