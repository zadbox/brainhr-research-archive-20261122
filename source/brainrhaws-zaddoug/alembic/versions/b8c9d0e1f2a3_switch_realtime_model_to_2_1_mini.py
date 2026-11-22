"""switch realtime interviews to GPT-Realtime-2.1 mini

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-12 00:00:00.000000
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PROCESS_ID = "realtime_interview_live"
_TARGET_MODEL = "gpt-realtime-2.1-mini"


def _settings_table() -> sa.TableClause:
    return sa.table(
        "llm_process_settings",
        sa.column("process_id", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("model", sa.String()),
        sa.column("updated_by_user_id", sa.String()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("llm_process_settings"):
        return

    settings = _settings_table()
    existing = bind.execute(
        sa.select(settings.c.process_id).where(settings.c.process_id == _PROCESS_ID)
    ).first()
    values = {
        "provider": "openai",
        "model": _TARGET_MODEL,
        "updated_by_user_id": None,
        "updated_at": datetime.now(timezone.utc),
    }
    if existing:
        bind.execute(
            settings.update().where(settings.c.process_id == _PROCESS_ID).values(**values)
        )
        return

    bind.execute(settings.insert().values(process_id=_PROCESS_ID, **values))


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("llm_process_settings"):
        return

    settings = _settings_table()
    bind.execute(
        settings.update()
        .where(
            settings.c.process_id == _PROCESS_ID,
            settings.c.model == _TARGET_MODEL,
        )
        .values(
            provider="openai",
            model="gpt-realtime-1.5",
            updated_by_user_id=None,
            updated_at=datetime.now(timezone.utc),
        )
    )
