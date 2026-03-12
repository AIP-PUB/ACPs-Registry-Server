"""add is_ontology field to agent table

Revision ID: e2f3a4b5c6d7
Revises: d1a2b3c4e5f6
Create Date: 2025-11-28 14:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1a2b3c4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加 is_ontology 字段到 agent 表"""
    # 添加 is_ontology 列，默认值为 False
    # False = 传统 Agent（本体与实体合一）或实体
    # True = 本体，可以派生实体
    op.add_column(
        "agent",
        sa.Column(
            "is_ontology",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 创建索引以加速按 is_ontology 过滤的查询
    op.create_index(
        "ix_agent_is_ontology",
        "agent",
        ["is_ontology"],
    )


def downgrade() -> None:
    """移除 is_ontology 字段"""
    op.drop_index("ix_agent_is_ontology", table_name="agent")
    op.drop_column("agent", "is_ontology")
