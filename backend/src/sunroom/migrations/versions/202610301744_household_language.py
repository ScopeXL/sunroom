"""household: language

Revision ID: 202610301744
Revises: 202610282014
Create Date: 2026-10-30 17:44:00 UTC

Forward-only: never edit this file once it is listed in released.lock.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '202610301744'
down_revision: str | Sequence[str] | None = '202610282014'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Settings → Household → Language (ADR 0043): every household so far speaks English.
    with op.batch_alter_table('household', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('language', sa.String(length=16), nullable=False, server_default='en')
        )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only; restore the pre-migration backup.")
