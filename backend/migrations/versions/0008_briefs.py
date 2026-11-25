"""In-app subscriptions and periodic report manifests."""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('brief_subscriptions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('scenario', sa.String(40), nullable=False),
        sa.Column('frequency', sa.String(10), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('last_cutoff', sa.DateTime(timezone=True), nullable=False),
        sa.Column('next_due', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'scenario', name='uq_brief_subscription_user_scenario'))
    op.create_index('ix_brief_subscription_due','brief_subscriptions',['active','next_due'])
    op.create_table('brief_issues',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('subscription_id', sa.String(36), sa.ForeignKey('brief_subscriptions.id'), nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('report_ids', sa.JSON(), nullable=False),
        sa.Column('truncated', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_brief_issue_subscription_created','brief_issues',['subscription_id','created_at'])


def downgrade():
    op.drop_index('ix_brief_issue_subscription_created',table_name='brief_issues')
    op.drop_table('brief_issues')
    op.drop_index('ix_brief_subscription_due',table_name='brief_subscriptions')
    op.drop_table('brief_subscriptions')
