"""add_webhook_table

Revision ID: aad447233342
Revises: 4217e3f408a8
Create Date: 2025-08-20 03:10:55.264623

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "aad447233342"
down_revision: Union[str, None] = "4217e3f408a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add webhook table for DRC protocol webhook functionality"""
    # NOTE: This table already exists in the database, so we skip creation
    # but document the expected structure for reference:
    #
    # op.create_table('webhook',
    #     sa.Column('id', sa.String(length=50), primary_key=True, nullable=False),
    #     sa.Column('url', sa.String(length=2000), nullable=False),
    #     sa.Column('secret', sa.String(length=500), nullable=False),
    #     sa.Column('types', sa.String(length=255), nullable=False),
    #     sa.Column('events', sa.String(length=255), nullable=False),
    #     sa.Column('description', sa.String(length=500), nullable=True),
    #     sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
    #     sa.Column('failure_count', sa.Integer(), nullable=False, server_default='0'),
    #     sa.Column('next_retry_at', sa.TIMESTAMP(timezone=True), nullable=True),
    #     sa.Column('last_triggered_at', sa.TIMESTAMP(timezone=True), nullable=True),
    #     sa.Column('last_success_at', sa.TIMESTAMP(timezone=True), nullable=True),
    #     sa.Column('last_failure_at', sa.TIMESTAMP(timezone=True), nullable=True),
    #     sa.Column('last_failure_reason', sa.Text(), nullable=True),
    #     sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
    #     sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False),
    # )
    pass


def downgrade() -> None:
    """Remove webhook table"""
    # op.drop_table('webhook')
    pass
