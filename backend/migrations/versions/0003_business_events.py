"""Private business events for candidate association."""
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE business_events (
        id varchar(36) PRIMARY KEY, owner_id varchar(36) NOT NULL REFERENCES users(id),
        scenario varchar(40) NOT NULL, title varchar(160) NOT NULL,
        start varchar(10) NOT NULL, "end" varchar(10) NOT NULL,
        scope json NOT NULL, source varchar(200) NOT NULL, created_at timestamptz NOT NULL
    )""")
    op.execute('CREATE INDEX ix_business_events_owner_id ON business_events(owner_id)')
    op.execute('CREATE INDEX ix_business_events_scenario ON business_events(scenario)')


def downgrade():
    op.drop_table('business_events')
