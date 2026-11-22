from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class ApplicationDB(SQLModel, table=True):
    __tablename__ = "applications"

    id: Optional[int] = Field(default=None, primary_key=True)
    enterprise_id: str = Field(index=True, nullable=False)
    talent_profile_id: int = Field(foreign_key="talent_profiles.id", index=True, nullable=False)
    resume_version_id: Optional[int] = Field(foreign_key="resume_versions.id", default=None, index=True)
    project_id: str = Field(index=True, nullable=False)
    status: str = Field(default="new")
    created_at: datetime = Field(default_factory=datetime.utcnow)
