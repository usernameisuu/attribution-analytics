"""Create only the dedicated test role/database on the specified development VM.

The operator supplies ATTRIBUTION_TEST_ADMIN_DATABASE_URL and
ATTRIBUTION_TEST_ROLE_PASSWORD in the ignored file backend/.env.test-admin.
The URL must use a PostgreSQL administrator account. Check the database
server's statement and extension logging policies before running: role DDL
may be logged by the server independently of this script.
No existing role, password, database, grant or data is altered.
"""
from pathlib import Path
from dotenv import dotenv_values
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def main():
    path = Path(__file__).resolve().parent / '.env.test-admin'
    if not path.is_file():
        raise SystemExit('Missing backend/.env.test-admin; provide the test provisioning administrator URL locally.')
    configuration = dotenv_values(path)
    raw = configuration.get('ATTRIBUTION_TEST_ADMIN_DATABASE_URL')
    if not raw:
        raise SystemExit('Missing ATTRIBUTION_TEST_ADMIN_DATABASE_URL.')
    password = configuration.get('ATTRIBUTION_TEST_ROLE_PASSWORD')
    if not password or len(password) < 24 or len(password) > 128:
        raise SystemExit('Provide a randomly generated test role password of 24–128 characters locally.')
    try:
        url = make_url(raw)
        if (url.drivername != 'postgresql+psycopg' or url.host != '192.168.100.101'
                or (url.port or 5432) != 5432 or url.query or not url.username or not url.password
                or not url.database or url.database == 'attribution_test'):
            raise ValueError('unexpected target or connection options')
        engine = create_engine(url, isolation_level='AUTOCOMMIT', connect_args={'connect_timeout': 5})
        try:
            with engine.connect() as connection:
                role = connection.execute(text('SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user')).one()
                if not (role.rolsuper or (role.rolcreatedb and role.rolcreaterole)):
                    raise RuntimeError('administrator needs both CREATEDB and CREATEROLE')
                exists = connection.execute(text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='attribution_test'), EXISTS (SELECT 1 FROM pg_database WHERE datname='attribution_test')")).one()
                if any(exists):
                    raise RuntimeError('test role or database already exists; stopped without changes')
                statement = sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                    sql.Identifier('attribution_test'), sql.Literal(password))
                connection.connection.driver_connection.execute(statement)
                print('Created dedicated test role.')
                try:
                    connection.exec_driver_sql('CREATE DATABASE attribution_test OWNER attribution_test')
                except Exception:
                    print('Database creation failed; the newly created test role remains. Inspect before retrying.')
                    raise
                print('Created dedicated test database.')
        finally:
            engine.dispose()
    except Exception as exc:
        # Do not print exception text, which may contain connection details.
        raise SystemExit(f'Provisioning stopped: {type(exc).__name__}. No existing object was changed.') from None


if __name__ == '__main__':
    main()
