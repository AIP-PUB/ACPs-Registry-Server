"""Change agent.aic to unbounded varchar

Revision ID: a7c9d2e4f6b8
Revises: 1b2c3d4e5f67
Create Date: 2026-01-13

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7c9d2e4f6b8"
down_revision: Union[str, None] = "1b2c3d4e5f67"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    AIC 在当前实现中为不定长点分标识，因此 DB 字段使用不指定长度的 VARCHAR。
    """
    op.alter_column(
        "agent",
        "aic",
        existing_type=sa.String(length=32),
        type_=sa.String(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema.

    WARNING: If values longer than 32 exist, they may be truncated by the database.
    """
    op.alter_column(
        "agent",
        "aic",
        existing_type=sa.String(),
        type_=sa.String(length=32),
        existing_nullable=True,
    )
