"""driver aadhaar last 4 digits

Revision ID: b41c7d2e9a10
Revises: 8f3783309bf2
Create Date: 2026-10-15 19:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b41c7d2e9a10'
down_revision: Union[str, Sequence[str], None] = '8f3783309bf2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('driver_profiles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('aadhaar_last4', sa.String(length=4), nullable=True))
        batch_op.add_column(sa.Column('aadhaar_source', sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('driver_profiles', schema=None) as batch_op:
        batch_op.drop_column('aadhaar_source')
        batch_op.drop_column('aadhaar_last4')
