"""Add memberships table

Revision ID: 1ef8b8e5bc29
Revises: c4e1ddf46216
Create Date: 2026-04-11 19:03:00.000000

CORR-001: MembershipDB existe dans brainrh/models/auth.py depuis BMT-NEXT-002
mais la migration initiale (c4e1ddf46216) ne créait que tenants et users.
Cette migration crée la table memberships de manière idempotente.

Contraintes:
- Compatible SQLite (pas d'Enum type standalone, UniqueConstraint inline)
- FK vers users.id déjà créée par c4e1ddf46216
- Downgrade propre sans cascade destructive
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '1ef8b8e5bc29'
down_revision: Union[str, Sequence[str], None] = 'c4e1ddf46216'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the memberships table.

    Colonnes minimales définies dans CORR-001:
    - id          : string primary key (UUID)
    - user_id     : string non-null, indexé, FK users.id
    - enterprise_id: string non-null, indexé
    - role        : enum/string compatible UserRole
    - scopes_json : string non-null default "[]"
    - is_active   : bool non-null default true
    - created_at  : datetime non-null

    Contrainte unique: (user_id, enterprise_id) — un user ne peut avoir
    qu'un seul membership actif par enterprise.
    """
    # Vérifier l'existence pour rendre idempotent (si init_db() a déjà matérialisé)
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'memberships' in inspector.get_table_names():
        # La table 'memberships' a déjà été créée par un appel hors Alembic (ex: init_db)
        return

    dialect_name = bind.dialect.name
    if dialect_name == 'postgresql':
        # Sur PostgreSQL le type 'userrole' est déjà défini. `create_type=False` est 
        # requis, mais le sa.Enum l'ignore. Il faut utiliser postgresql.ENUM
        role_type = postgresql.ENUM('platform_admin', 'enterprise_admin', 'recruiter', 'viewer', name='userrole', create_type=False)
    else:
        # Sur SQLite, Enum générique passe
        role_type = sa.Enum('platform_admin', 'enterprise_admin', 'recruiter', 'viewer', name='userrole')

    op.create_table(
        'memberships',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('enterprise_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            'role',
            role_type,
            nullable=False,
            server_default='viewer',
        ),
        sa.Column(
            'scopes_json',
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default='[]',
        ),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        # FK vers users.id créé par la migration précédente
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_memberships_user_id'),
        sa.PrimaryKeyConstraint('id'),
        # Contrainte unique: un user = un membership par enterprise
        sa.UniqueConstraint('user_id', 'enterprise_id', name='uq_memberships_user_enterprise'),
    )
    # Index séparés pour les requêtes filtrées enterprise_id et user_id
    op.create_index(
        op.f('ix_memberships_user_id'),
        'memberships',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_memberships_enterprise_id'),
        'memberships',
        ['enterprise_id'],
        unique=False,
    )


def downgrade() -> None:
    """Drop the memberships table cleanly."""
    op.drop_index(op.f('ix_memberships_enterprise_id'), table_name='memberships')
    op.drop_index(op.f('ix_memberships_user_id'), table_name='memberships')
    op.drop_table('memberships')
