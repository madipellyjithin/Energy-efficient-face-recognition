from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _to_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    camera_index: int = int(os.getenv("CAMERA_INDEX", "0"))
    detector_model_path: Path = BASE_DIR / os.getenv(
        "DETECTOR_MODEL_PATH", "models/face_detection_yunet_2023mar.onnx"
    )
    recognizer_model_path: Path = BASE_DIR / os.getenv(
        "RECOGNIZER_MODEL_PATH", "models/face_recognition_sface_2021dec.onnx"
    )
    known_faces_dir: Path = BASE_DIR / os.getenv("KNOWN_FACES_DIR", "data/known_faces")
    attendance_log_path: Path = BASE_DIR / os.getenv("ATTENDANCE_LOG_PATH", "data/attendance.csv")
    match_threshold: float = float(os.getenv("MATCH_THRESHOLD", "0.55"))
    frame_width: int = int(os.getenv("FRAME_WIDTH", "640"))
    frame_height: int = int(os.getenv("FRAME_HEIGHT", "480"))
    auto_alert_on_unknown: bool = _to_bool(os.getenv("AUTO_ALERT_ON_UNKNOWN"), True)
    capture_cooldown_seconds: float = float(os.getenv("CAPTURE_COOLDOWN_SECONDS", "3"))
    attendance_cooldown_seconds: float = float(os.getenv("ATTENDANCE_COOLDOWN_SECONDS", "10"))
    esp32_api_base_url: str = os.getenv("ESP32_API_BASE_URL", "").strip()
    esp32_discovery_enabled: bool = _to_bool(os.getenv("ESP32_DISCOVERY_ENABLED"), True)
    esp32_mdns_service: str = os.getenv("ESP32_MDNS_SERVICE", "_edgeface._tcp.local.")
    esp32_scan_timeout_seconds: float = float(os.getenv("ESP32_SCAN_TIMEOUT_SECONDS", "4"))


settings = Settings()
