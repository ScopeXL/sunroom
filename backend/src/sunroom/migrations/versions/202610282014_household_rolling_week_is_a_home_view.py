"""household: rolling week is a home view, hours by default

Revision ID: 202610282014
Revises: 202610211809
Create Date: 2026-10-28 20:14:00 UTC

Forward-only: never edit this file once it is listed in released.lock.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '202610282014'
down_revision: str | Sequence[str] | None = '202610211809'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rolling week is a view of its own from 0.17.0 (ADR 0042), not a switch on the Week view: a
    # household that had it on, starting on Week, starts on Rolling Week now.
    op.execute(
        "UPDATE household SET display_home_view = 'rolling'"
        " WHERE display_rolling_week = 1 AND display_home_view = 'week'"
    )
    # Week with Hours is a new household's start. The household row exists from the first
    # migration on, so a household not set up yet moves to Hours; one set up keeps its layout.
    op.execute("UPDATE household SET display_week_layout = 'hours' WHERE onboarded_at IS NULL")
    with op.batch_alter_table('household', schema=None) as batch_op:
        batch_op.alter_column(
            'display_week_layout',
            existing_type=sa.String(length=8),
            existing_nullable=False,
            server_default='hours',
        )
        batch_op.drop_column('display_rolling_week')


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only; restore the pre-migration backup.")
