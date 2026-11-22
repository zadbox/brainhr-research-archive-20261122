from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class LLMProcessSettingDB(SQLModel, table=True):
    """Provider/model override for a named LLM-enabled BrainRH process."""

    __tablename__ = "llm_process_settings"

    process_id: str = Field(primary_key=True)
    provider: str = Field(index=True)
    model: str
    updated_by_user_id: Optional[str] = Field(default=None, foreign_key="users.id")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
