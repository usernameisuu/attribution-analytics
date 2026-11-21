"""Initial account, analysis snapshot and audit schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users", sa.Column("id",sa.String(36),primary_key=True), sa.Column("username",sa.String(80),nullable=False,unique=True), sa.Column("password_hash",sa.String(256),nullable=False), sa.Column("role",sa.String(24),nullable=False), sa.Column("domains",sa.JSON(),nullable=False), sa.Column("active",sa.Boolean(),nullable=False))
    op.create_table("login_sessions", sa.Column("token_hash",sa.String(64),primary_key=True), sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id"),nullable=False), sa.Column("csrf",sa.String(64),nullable=False), sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_login_sessions_user_id","login_sessions",["user_id"])
    op.create_table("analysis_sessions",sa.Column("id",sa.String(36),primary_key=True),sa.Column("owner_id",sa.String(36),sa.ForeignKey("users.id"),nullable=False),sa.Column("scenario",sa.String(40),nullable=False),sa.Column("title",sa.String(160),nullable=False),sa.Column("snapshot",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_analysis_sessions_owner_id","analysis_sessions",["owner_id"])
    op.create_table("audit_events",sa.Column("id",sa.String(36),primary_key=True),sa.Column("actor_id",sa.String(36)),sa.Column("action",sa.String(60),nullable=False),sa.Column("object_id",sa.String(160),nullable=False),sa.Column("details",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_audit_events_action","audit_events",["action"])
    op.create_index("ix_audit_action_object_time","audit_events",["action","object_id","created_at"])


def downgrade():
    for table in ("audit_events","analysis_sessions","login_sessions","users"):
        op.drop_table(table)
