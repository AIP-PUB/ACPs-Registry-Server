"""remove_agent_protocol_support_flags

Revision ID: 9d2c1a7b3e4f
Revises: a7c9d2e4f6b8
Create Date: 2026-01-20 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9d2c1a7b3e4f"
down_revision: Union[str, None] = "a7c9d2e4f6b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("agent", "is_acp_support")
    op.drop_column("agent", "is_a2a_support")
    op.drop_column("agent", "is_anp_support")


def downgrade() -> None:
    op.add_column(
        "agent",
        sa.Column(
            "is_anp_support",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "agent",
        sa.Column(
            "is_a2a_support",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "agent",
        sa.Column(
            "is_acp_support",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 移除 server_default，保持与历史表结构一致（由应用层决定默认值）
    op.alter_column("agent", "is_anp_support", server_default=None)
    op.alter_column("agent", "is_a2a_support", server_default=None)
    op.alter_column("agent", "is_acp_support", server_default=None)
