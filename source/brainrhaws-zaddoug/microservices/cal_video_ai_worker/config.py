from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


SERVICE_DIR = Path(__file__).resolve().parent
ROOT_ENV_PATH = SERVICE_DIR.parents[1] / ".env"
SERVICE_ENV_PATH = SERVICE_DIR / ".env"

load_dotenv(ROOT_ENV_PATH)
load_dotenv(SERVICE_ENV_PATH, override=True)


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WorkerSettings:
    backend_base_url: str
    worker_event_secret: str
    openai_api_key: str
    realtime_model: str
    ai_display_name: str
    wrap_up_seconds: int
    candidate_absence_grace_seconds: int
    poll_interval_seconds: float
    capture_device: str
    mic_device: str
    pulse_sink_name: str
    pulse_source_name: str
    audio_sample_rate: int
    audio_chunk_ms: int
    chromium_executable_path: str | None
    headless: bool
    live_smoke_enabled: bool
    local_recording_enabled: bool
    local_recording_dir: str
    local_recording_host_dir: str | None
    local_recording_capture_size: str
    local_recording_resolution: str
    local_recording_video_size: str
    local_recording_framerate: int


def _recording_video_size_for_resolution(resolution: str) -> str:
    normalized = resolution.strip().lower()
    if normalized in {"144", "144p"}:
        return "256x144"
    if normalized in {"360", "360p"}:
        return "640x360"
    if normalized in {"720", "720p"}:
        return "1280x720"
    return "640x360"


def get_settings() -> WorkerSettings:
    recording_resolution = os.getenv("CAL_VIDEO_LOCAL_RECORDING_RESOLUTION", "360p").strip() or "360p"
    recording_video_size = (
        os.getenv("CAL_VIDEO_LOCAL_RECORDING_VIDEO_SIZE", "").strip()
        or _recording_video_size_for_resolution(recording_resolution)
    )
    return WorkerSettings(
        backend_base_url=os.getenv("BRAINRH_BACKEND_URL", "http://localhost:8000").rstrip("/"),
        worker_event_secret=os.getenv("BRAINRH_WORKER_EVENT_SECRET", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        realtime_model=os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1-mini").strip(),
        ai_display_name=os.getenv("CAL_VIDEO_AI_DISPLAY_NAME", "BrainRH AI Interviewer"),
        wrap_up_seconds=int(os.getenv("CAL_VIDEO_WRAP_UP_SECONDS", "180")),
        candidate_absence_grace_seconds=int(os.getenv("CAL_VIDEO_CANDIDATE_ABSENCE_GRACE_SECONDS", "60")),
        poll_interval_seconds=float(os.getenv("CAL_VIDEO_POLL_INTERVAL_SECONDS", "2")),
        capture_device=os.getenv("CAL_VIDEO_CAPTURE_DEVICE", "brainrh_calvideo.monitor").strip(),
        mic_device=os.getenv("CAL_VIDEO_MIC_DEVICE", "brainrh_ai_mic").strip(),
        pulse_sink_name=os.getenv("CAL_VIDEO_PULSE_SINK_NAME", "brainrh_calvideo").strip(),
        pulse_source_name=os.getenv("CAL_VIDEO_PULSE_SOURCE_NAME", "brainrh_ai_mic").strip(),
        audio_sample_rate=int(os.getenv("CAL_VIDEO_AUDIO_SAMPLE_RATE", "24000")),
        audio_chunk_ms=int(os.getenv("CAL_VIDEO_AUDIO_CHUNK_MS", "100")),
        chromium_executable_path=os.getenv("CAL_VIDEO_CHROMIUM_EXECUTABLE") or None,
        headless=os.getenv("CAL_VIDEO_HEADLESS", "true").strip().lower() not in {"0", "false", "no"},
        live_smoke_enabled=_env_flag("CAL_VIDEO_LIVE_SMOKE_ENABLED"),
        local_recording_enabled=_env_flag("CAL_VIDEO_LOCAL_RECORDING_ENABLED", default=True),
        local_recording_dir=os.getenv("CAL_VIDEO_LOCAL_RECORDING_DIR", "/tmp/brainrh-cal-video-recordings"),
        local_recording_host_dir=os.getenv("CAL_VIDEO_LOCAL_RECORDING_HOST_DIR") or None,
        local_recording_capture_size=os.getenv("CAL_VIDEO_LOCAL_RECORDING_CAPTURE_SIZE", "1280x720").strip()
        or "1280x720",
        local_recording_resolution=recording_resolution,
        local_recording_video_size=recording_video_size,
        local_recording_framerate=int(os.getenv("CAL_VIDEO_LOCAL_RECORDING_FRAMERATE", "10")),
    )
