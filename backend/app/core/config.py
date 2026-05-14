from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    project_root: Path = Path(__file__).resolve().parents[3]
    checkpoint_path: Path = project_root / "checkpoint-best.pth"
    upload_dir: Path = project_root / "backend" / "storage" / "uploads"
    output_dir: Path = project_root / "backend" / "storage" / "outputs"
    max_upload_mb: int = 500
    allow_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    class_names: list[str] = ["neutral", "smile", "frown", "blink", "surprise"]
    gemini_model: str = "gemini-2.5-flash"
    gemini_temperature: float = 0.4

    # Remote inference services (usually accessed via SSH tunnel: localhost:9000/9001)
    remote_base_url: str = "http://localhost:9000"
    remote_realtime_base_url: str = "http://localhost:9001"

    # Protocol upgrade: prefer raw JPEG body to avoid multipart parsing overhead on remote realtime server.
    # When enabled, backend will try /realtime/predict-frame-raw first and fallback to multipart.
    remote_realtime_use_raw: bool = True

    # Protocol upgrade (recommended): prefer WebSocket single-connection streaming for realtime frames.
    # Backend will try WS first, then fallback to HTTP raw/multipart.
    remote_realtime_use_ws: bool = True
    remote_realtime_ws_url: str = "ws://localhost:9002/ws/realtime"


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)
