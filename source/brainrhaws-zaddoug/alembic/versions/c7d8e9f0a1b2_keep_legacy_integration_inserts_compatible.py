"""keep legacy integration account inserts compatible

Revision ID: c7d8e9f0a1b2
Revises: 9c1d2e3f4a5b
Create Date: 2026-07-14 23:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "9c1d2e3f4a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FUNCTION_NAME = "brainrh_fill_legacy_integration_scope"
_TRIGGER_NAME = "trg_integration_accounts_legacy_scope"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    inspector = sa.inspect(bind)
    if not inspector.has_table("integration_accounts"):
        return

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION_NAME}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
        BEGIN
            IF NEW.scope_kind IS NULL
               AND NEW.scope_id IS NULL
               AND NEW.enterprise_id IS NOT NULL THEN
                NEW.scope_kind := 'enterprise_legacy';
                NEW.scope_id := NEW.enterprise_id;
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER_NAME}
        BEFORE INSERT ON integration_accounts
        FOR EACH ROW
        EXECUTE FUNCTION {_FUNCTION_NAME}()
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    if sa.inspect(bind).has_table("integration_accounts"):
        op.execute(
            f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON integration_accounts"
        )
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION_NAME}()")
