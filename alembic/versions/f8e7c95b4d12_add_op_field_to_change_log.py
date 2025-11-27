"""add_op_field_to_change_log

Revision ID: f8e7c95b4d12
Revises: aad447233342
Create Date: 2025-01-27 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f8e7c95b4d12"
down_revision: Union[str, None] = "aad447233342"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add op column to change_log table with default value 'upsert'
    op.add_column(
        "change_log",
        sa.Column("op", sa.String(length=10), nullable=False, server_default="upsert"),
    )
    # Add index on op column
    op.create_index(op.f("ix_change_log_op"), "change_log", ["op"], unique=False)


def downgrade() -> None:
    # Remove index and column
    op.drop_index(op.f("ix_change_log_op"), table_name="change_log")
    op.drop_column("change_log", "op")
