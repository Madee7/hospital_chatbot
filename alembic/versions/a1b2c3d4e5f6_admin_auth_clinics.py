"""admin_auth_clinics

Revision ID: a1b2c3d4e5f6
Revises: 82401df5e5b2
Create Date: 2026-08-15

- admin_users.password_hash
- admin_user_clinics join table
- backfill password hashes from ADMIN_DASHBOARD_PASSWORD (bootstrap)
- normalize legacy role 'admin' → company_admin
"""

from __future__ import annotations

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "82401df5e5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "admin_users",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )
    op.create_table(
        "admin_user_clinics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("clinic_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["admin_users.user_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinics.clinic_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("user_id", "clinic_id", name="uq_admin_user_clinic"),
    )
    op.create_index(
        "idx_admin_user_clinic_user", "admin_user_clinics", ["user_id"]
    )
    op.create_index(
        "idx_admin_user_clinic_clinic", "admin_user_clinics", ["clinic_id"]
    )

    bind = op.get_bind()
    bootstrap = (
        os.getenv("ADMIN_DASHBOARD_PASSWORD")
        or os.getenv("ADMIN_BOOTSTRAP_PASSWORD")
        or "admin123"
    )
    # Import after bind so offline revision listing still works.
    from app.core.security import hash_password

    hashed = hash_password(bootstrap)
    bind.execute(
        sa.text(
            "UPDATE admin_users SET password_hash = :h "
            "WHERE password_hash IS NULL OR password_hash = ''"
        ),
        {"h": hashed},
    )
    bind.execute(
        sa.text(
            "UPDATE admin_users SET role = 'company_admin' "
            "WHERE role IN ('admin', 'Admin', 'ADMIN')"
        )
    )


def downgrade() -> None:
    op.drop_index("idx_admin_user_clinic_clinic", table_name="admin_user_clinics")
    op.drop_index("idx_admin_user_clinic_user", table_name="admin_user_clinics")
    op.drop_table("admin_user_clinics")
    op.drop_column("admin_users", "password_hash")
