"""change changelog payload to jsonb

Revision ID: 1b2c3d4e5f67
Revises: f8e7c95b4d12
Create Date: 2025-11-28 23:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1b2c3d4e5f67"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """将 change_log.payload 从 TEXT 调整为 JSONB"""
    op.execute(
        """
        ALTER TABLE change_log
        ALTER COLUMN payload TYPE JSONB
        USING CASE
            WHEN payload IS NULL THEN NULL
            WHEN payload = '' THEN NULL
            ELSE payload::jsonb
        END
        """
    )


def downgrade() -> None:
    """将 change_log.payload 从 JSONB 恢复为 TEXT"""
    op.execute(
        """
        ALTER TABLE change_log
        ALTER COLUMN payload TYPE TEXT
        USING payload::text
        """
    )
