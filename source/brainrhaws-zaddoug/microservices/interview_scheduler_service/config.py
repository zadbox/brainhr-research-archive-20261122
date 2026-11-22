from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


SERVICE_DIR = Path(__file__).resolve().parent
ROOT_ENV_PATH = SERVICE_DIR.parents[1] / ".env"
SERVICE_ENV_PATH = SERVICE_DIR / ".env"

load_dotenv(ROOT_ENV_PATH)
load_dotenv(SERVICE_ENV_PATH, override=True)


@dataclass(frozen=True)
class Settings:
    service_name: str
    service_port: int
    database_path: str
    calcom_base_url: str
    calcom_api_key: str
    calcom_api_version: str
    calcom_artifact_api_version: str
    calcom_transcript_api_version: str
    calcom_event_type_id: int | None
    calcom_event_type_slug: str
    calcom_username: str
    calcom_team_slug: str
    calcom_organization_slug: str
    organizer_email: str
    default_timezone: str
    default_duration_minutes: int

    @property
    def calcom_configured(self) -> bool:
        return bool(self.calcom_api_key) and (
            self.calcom_event_type_id is not None
            or bool(self.calcom_event_type_slug and (self.calcom_username or self.calcom_team_slug))
        )


def _read_int(name: str) -> int | None:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return None
    return int(raw_value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        service_name=os.getenv("SCHEDULER_SERVICE_NAME", "brainrh-interview-scheduler"),
        service_port=int(os.getenv("SCHEDULER_SERVICE_PORT", "8010")),
        database_path=os.getenv(
            "SCHEDULER_DATABASE_PATH",
            "microservices/interview_scheduler_service/data/scheduler.db",
        ),
        calcom_base_url=os.getenv("CALCOM_BASE_URL", "https://api.cal.com/v2"),
        calcom_api_key=os.getenv("CALCOM_API_KEY", "").strip(),
        calcom_api_version=os.getenv("CALCOM_API_VERSION", "2026-02-25"),
        calcom_artifact_api_version=os.getenv(
            "CALCOM_ARTIFACT_API_VERSION",
            os.getenv("CALCOM_API_VERSION", "2026-02-25"),
        ),
        calcom_transcript_api_version=os.getenv(
            "CALCOM_TRANSCRIPT_API_VERSION",
            os.getenv("CALCOM_API_VERSION", "2026-02-25"),
        ),
        calcom_event_type_id=_read_int("CALCOM_EVENT_TYPE_ID"),
        calcom_event_type_slug=os.getenv("CALCOM_EVENT_TYPE_SLUG", "").strip(),
        calcom_username=os.getenv("CALCOM_USERNAME", "").strip(),
        calcom_team_slug=os.getenv("CALCOM_TEAM_SLUG", "").strip(),
        calcom_organization_slug=os.getenv("CALCOM_ORGANIZATION_SLUG", "").strip(),
        organizer_email=os.getenv("SCHEDULER_ORGANIZER_EMAIL", "").strip(),
        default_timezone=os.getenv("SCHEDULER_DEFAULT_TIMEZONE", "Europe/Paris").strip(),
        default_duration_minutes=int(os.getenv("SCHEDULER_DEFAULT_DURATION_MINUTES", "45")),
    )
