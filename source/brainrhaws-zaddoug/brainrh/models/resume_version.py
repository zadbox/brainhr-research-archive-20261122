from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class ResumeVersionDB(SQLModel, table=True):
    __tablename__ = "resume_versions"

    id: Optional[int] = Field(default=None, primary_key=True)
    enterprise_id: str = Field(index=True, nullable=False)
    talent_profile_id: int = Field(foreign_key="talent_profiles.id", index=True, nullable=False)
    version_number: int = Field(default=1)
    storage_path: Optional[str] = Field(default=None)
    parsed_json_str: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
