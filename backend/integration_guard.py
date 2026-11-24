"""Fail closed before integration tests or test migrations touch PostgreSQL."""
import os
from urllib.parse import urlsplit, unquote


def validate_url(value):
    try:
        url = urlsplit(value)
        _ = url.port  # Reject malformed ports.
        valid = (url.scheme == "postgresql+psycopg" and bool(url.hostname)
                 and unquote(url.username or "") == "attribution_test"
                 and url.path == "/attribution_test" and not url.query and not url.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise RuntimeError("Integration tests require PostgreSQL database and user attribution_test, without URL options")


def check_target():
    url = os.environ.get("ATTRIBUTION_TEST_DATABASE_URL", "")
    validate_url(url)
    if os.environ.get("ATTRIBUTION_DATABASE_URL") != url:
        raise RuntimeError("ATTRIBUTION_DATABASE_URL must exactly match ATTRIBUTION_TEST_DATABASE_URL")
    from sqlalchemy import create_engine, text
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            actual = connection.execute(text("SELECT current_database(), current_user, session_user")).one()
            if tuple(actual) != ("attribution_test",) * 3:
                raise RuntimeError("Connected database or role does not match the isolated test target")
    finally:
        engine.dispose()
