"""Store immutable, inactive metric definition drafts."""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('metric_drafts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('author_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('scenario', sa.String(40), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('definitions', sa.JSON(), nullable=False),
        sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_metric_drafts_scenario_created', 'metric_drafts', ['scenario', 'created_at'])


def downgrade():
    op.drop_index('ix_metric_drafts_scenario_created', table_name='metric_drafts')
    op.drop_table('metric_drafts')
