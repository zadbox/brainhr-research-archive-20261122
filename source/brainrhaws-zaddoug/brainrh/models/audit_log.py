from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class AuditLogDB(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    enterprise_id: str = Field(index=True, nullable=False)
    actor_user_id: Optional[str] = Field(default=None, index=True)
    action: str = Field(index=True, nullable=False)
    resource_type: str = Field(index=True, nullable=False)
    resource_id: str = Field(index=True, nullable=False)
    metadata_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
