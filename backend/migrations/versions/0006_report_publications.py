"""Publish a frozen report to users authorized for its business line."""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('report_publications',
        sa.Column('report_id', sa.String(36), sa.ForeignKey('report_archives.id'), primary_key=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False))


def downgrade():
    op.drop_table('report_publications')
