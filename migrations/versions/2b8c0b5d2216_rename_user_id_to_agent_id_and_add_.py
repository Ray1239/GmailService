"""rename user_id to agent_id and add agent_secrets

Revision ID: 2b8c0b5d2216
Revises: 469d24759452
Create Date: 2026-02-19 13:11:48.670917

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2b8c0b5d2216'
down_revision: Union[str, Sequence[str], None] = '469d24759452'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create agent_secrets table
    op.create_table('agent_secrets',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('agent_id', sa.String(length=50), nullable=False),
    sa.Column('service_name', sa.String(length=50), nullable=False),
    sa.Column('secret_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('agent_id', 'service_name', name='uq_agent_service')
    )

    # Rename user_id → agent_id in gmail_accounts
    op.drop_index(op.f('ix_gmail_accounts_user_id'), table_name='gmail_accounts')
    op.alter_column('gmail_accounts', 'user_id', new_column_name='agent_id')
    op.create_index(op.f('ix_gmail_accounts_agent_id'), 'gmail_accounts', ['agent_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Rename agent_id → user_id in gmail_accounts
    op.drop_index(op.f('ix_gmail_accounts_agent_id'), table_name='gmail_accounts')
    op.alter_column('gmail_accounts', 'agent_id', new_column_name='user_id')
    op.create_index(op.f('ix_gmail_accounts_user_id'), 'gmail_accounts', ['user_id'], unique=False)

    op.drop_table('agent_secrets')

