"""create change_log table and global_seq sequence

Revision ID: 60a9fc91f469
Revises: b49f5453e252
Create Date: 2025-08-19 23:58:57.835326

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "60a9fc91f469"
down_revision: Union[str, None] = "b49f5453e252"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 创建全局序列
    op.execute("CREATE SEQUENCE IF NOT EXISTS global_seq START WITH 1 INCREMENT BY 1")

    # 创建change_log表
    op.create_table(
        "change_log",
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("seq"),
    )

    # 设置seq列的默认值为序列的下一个值
    op.execute(
        "ALTER TABLE change_log ALTER COLUMN seq SET DEFAULT nextval('global_seq')"
    )

    # 创建索引
    op.create_index(op.f("ix_change_log_seq"), "change_log", ["seq"], unique=False)
    op.create_index(op.f("ix_change_log_type"), "change_log", ["type"], unique=False)
    op.create_index(op.f("ix_change_log_id"), "change_log", ["id"], unique=False)
    op.create_index(
        op.f("ix_change_log_version"), "change_log", ["version"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 删除索引
    op.drop_index(op.f("ix_change_log_version"), table_name="change_log")
    op.drop_index(op.f("ix_change_log_id"), table_name="change_log")
    op.drop_index(op.f("ix_change_log_type"), table_name="change_log")
    op.drop_index(op.f("ix_change_log_seq"), table_name="change_log")

    # 删除表
    op.drop_table("change_log")

    # 删除序列
    op.execute("DROP SEQUENCE IF EXISTS global_seq")
