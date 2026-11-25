"""Store report comments separately from frozen report snapshots."""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('report_comments',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('report_id', sa.String(36), sa.ForeignKey('report_archives.id'), nullable=False),
        sa.Column('author_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_report_comments_report_created', 'report_comments', ['report_id', 'created_at', 'id'])


def downgrade():
    op.drop_index('ix_report_comments_report_created', table_name='report_comments')
    op.drop_table('report_comments')
