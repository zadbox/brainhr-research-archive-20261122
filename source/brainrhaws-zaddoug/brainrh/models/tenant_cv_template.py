from datetime import datetime, timezone
import uuid
from typing import Optional

from sqlmodel import Field, SQLModel


class TenantCvTemplateDB(SQLModel, table=True):
    __tablename__ = "tenant_cv_templates"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    tenant_id: str = Field(foreign_key="tenants.id", index=True, nullable=False)
    name: str = Field(index=True)
    original_filename: str
    version: int = Field(default=1, nullable=False)
    storage_path: str
    content_hash: str = Field(index=True)
    metadata_json: str = Field(default="{}", nullable=False)
    is_valid: bool = Field(default=False, nullable=False)
    is_active: bool = Field(default=False, nullable=False)
    uploaded_by: str = Field(default="", nullable=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    activated_at: Optional[datetime] = Field(default=None, nullable=True)
