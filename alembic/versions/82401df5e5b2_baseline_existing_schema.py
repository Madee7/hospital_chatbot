"""baseline_existing_schema

Revision ID: 82401df5e5b2
Revises:
Create Date: 2026-07-27 14:04:34.248095

Baseline for databases that already match the current SQLAlchemy models
(historically created via Base.metadata.create_all).

- Existing DBs: run `alembic stamp head` once (do not re-create tables).
- Empty / new DBs: `alembic upgrade head` creates any missing tables.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "82401df5e5b2"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create any tables that are still missing (idempotent)."""
    # Import inside the function so Alembic can load revision metadata
    # without requiring a live DB connection for offline listing.
    from app.db.database import Base
    import app.models  # noqa: F401

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Drop all application tables (destructive — use only on throwaway DBs)."""
    from app.db.database import Base
    import app.models  # noqa: F401

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
