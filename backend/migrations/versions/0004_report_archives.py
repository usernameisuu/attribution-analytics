"""Store owner-scoped frozen report drafts."""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('report_archives',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('analysis_sessions.id'), nullable=False),
        sa.Column('scenario', sa.String(40), nullable=False),
        sa.Column('title', sa.String(160), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_report_archives_owner_session_created', 'report_archives', ['owner_id','session_id','created_at'])


def downgrade():
    op.drop_index('ix_report_archives_owner_session_created', table_name='report_archives')
    op.drop_table('report_archives')
