from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class TalentProfileDB(SQLModel, table=True):
    __tablename__ = "talent_profiles"

    id: Optional[int] = Field(default=None, primary_key=True)
    enterprise_id: str = Field(index=True, nullable=False)
    email: Optional[str] = Field(default=None, index=True)
    first_name: Optional[str] = Field(default=None)
    last_name: Optional[str] = Field(default=None)
    phone: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
