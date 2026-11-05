"""household: the check for new versions is on

Revision ID: 202611051718
Revises: 202610301744
Create Date: 2026-11-05 12:18:45.643215

Forward-only: never edit this file once it is listed in released.lock.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '202611051718'
down_revision: str | Sequence[str] | None = '202610301744'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The check for new versions is on by default (ADR 0046). The household row exists from the
    # first migration on, so this covers one not set up yet too. Nothing ever recorded a choice of
    # Off, so every household gets it; the CHANGELOG says so and the switch is in About.
    op.execute("UPDATE household SET update_check = 1")
    with op.batch_alter_table('household', schema=None) as batch_op:
        batch_op.alter_column(
            'update_check',
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.true(),
        )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only; restore the pre-migration backup.")
