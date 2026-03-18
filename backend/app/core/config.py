from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    project_root: Path = Path(__file__).resolve().parents[3]
    checkpoint_path: Path = project_root / "checkpoint-best.pth"
    upload_dir: Path = project_root / "backend" / "storage" / "uploads"
    output_dir: Path = project_root / "backend" / "storage" / "outputs"
    max_upload_mb: int = 200
    allow_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    class_names: list[str] = ["neutral", "smile", "frown", "blink", "surprise"]


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)
