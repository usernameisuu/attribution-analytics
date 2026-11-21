"""Immutable datasets, fenced queue and cumulative budget ledger."""
from alembic import op
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE dataset_versions (id varchar(36) PRIMARY KEY, owner_id varchar(36) NOT NULL REFERENCES users(id), scenario varchar(40) NOT NULL, name varchar(120) NOT NULL, source_kind varchar(16) NOT NULL, digest varchar(64) NOT NULL, rows json NOT NULL, created_at timestamptz NOT NULL, CONSTRAINT uq_dataset_digest UNIQUE(owner_id,scenario,digest));
CREATE INDEX ix_dataset_versions_scenario ON dataset_versions(scenario);
CREATE TABLE analysis_runs (id varchar(36) PRIMARY KEY, session_id varchar(36) NOT NULL REFERENCES analysis_sessions(id), owner_id varchar(36) NOT NULL REFERENCES users(id), dataset_id varchar(36) NOT NULL REFERENCES dataset_versions(id), request_key varchar(80) NOT NULL, request_hash varchar(64) NOT NULL, question varchar(2000) NOT NULL, scope json NOT NULL, parents json NOT NULL, mode varchar(16) NOT NULL, status varchar(24) NOT NULL, stage varchar(60) NOT NULL, attempts integer NOT NULL, fence varchar(64), lease_until timestamptz, sequence integer NOT NULL, result json, error text, created_at timestamptz NOT NULL, CONSTRAINT uq_run_request UNIQUE(owner_id,request_key));
CREATE INDEX ix_analysis_runs_session_id ON analysis_runs(session_id);
CREATE UNIQUE INDEX uq_run_active_session ON analysis_runs(session_id) WHERE status IN ('queued','running');
CREATE TABLE run_events (id varchar(36) PRIMARY KEY, run_id varchar(36) NOT NULL REFERENCES analysis_runs(id), sequence integer NOT NULL, payload json NOT NULL, created_at timestamptz NOT NULL, CONSTRAINT uq_run_event UNIQUE(run_id,sequence));
CREATE INDEX ix_run_events_run_id ON run_events(run_id);
CREATE TABLE budget_accounts (id varchar(36) PRIMARY KEY, limit_cny numeric(18,8) NOT NULL, spent_cny numeric(18,8) NOT NULL, reserved_cny numeric(18,8) NOT NULL, CONSTRAINT ck_budget_nonnegative CHECK(limit_cny>=0 AND spent_cny>=0 AND reserved_cny>=0));
INSERT INTO budget_accounts VALUES ('development',25,0,0);
CREATE TABLE model_calls (id varchar(36) PRIMARY KEY, run_id varchar(36) NOT NULL REFERENCES analysis_runs(id), state varchar(24) NOT NULL, reserved_cny numeric(18,8) NOT NULL, actual_cny numeric(18,8), price_version varchar(80) NOT NULL, usage json NOT NULL, created_at timestamptz NOT NULL);
"""


def upgrade():
    for statement in DDL.split(';'):
        if statement.strip(): op.execute(statement)


def downgrade():
    for table in ('model_calls','budget_accounts','run_events','analysis_runs','dataset_versions'):
        op.drop_table(table)
