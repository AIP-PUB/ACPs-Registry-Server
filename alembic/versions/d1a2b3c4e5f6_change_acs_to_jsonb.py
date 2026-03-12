"""change acs column from TEXT to JSONB

Revision ID: d1a2b3c4e5f6
Revises: 23c5f36f845a
Create Date: 2025-11-28 13:26:44.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "d1a2b3c4e5f6"
down_revision: Union[str, None] = "23c5f36f845a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """将 agent 表的 acs 列从 TEXT 改为 JSONB"""
    # 使用 USING 子句将现有 TEXT 数据转换为 JSONB
    op.execute(
        """
        ALTER TABLE agent 
        ALTER COLUMN acs TYPE JSONB 
        USING CASE 
            WHEN acs IS NULL THEN NULL 
            WHEN acs = '' THEN NULL
            ELSE acs::jsonb 
        END
        """
    )

    # 为 endPoints 数组中的 url 字段创建 GIN 索引，支持高效的 JSONB 查询
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_agent_acs_endpoints_url 
        ON agent USING GIN ((acs->'endPoints'))
        """
    )


def downgrade() -> None:
    """将 agent 表的 acs 列从 JSONB 改回 TEXT"""
    # 删除 GIN 索引
    op.execute("DROP INDEX IF EXISTS ix_agent_acs_endpoints_url")

    # 将 JSONB 转换回 TEXT
    op.execute(
        """
        ALTER TABLE agent 
        ALTER COLUMN acs TYPE TEXT 
        USING acs::text
        """
    )
