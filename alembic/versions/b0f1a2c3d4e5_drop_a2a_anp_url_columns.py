"""drop_a2a_anp_url_columns

Revision ID: b0f1a2c3d4e5
Revises: 9d2c1a7b3e4f
Create Date: 2026-01-25 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b0f1a2c3d4e5"
down_revision: Union[str, None] = "9d2c1a7b3e4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = inspector.get_columns(table_name)
    return any(col.get("name") == column_name for col in columns)


def upgrade() -> None:
    # 兼容不同环境：如果列不存在则跳过
    if _has_column("agent", "a2a_url"):
        op.drop_column("agent", "a2a_url")
    if _has_column("agent", "anp_url"):
        op.drop_column("agent", "anp_url")


def downgrade() -> None:
    op.add_column(
        "agent",
        sa.Column("a2a_url", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "agent",
        sa.Column("anp_url", sa.String(length=1000), nullable=True),
    )
