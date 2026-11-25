"""Authentication endpoint behavior without a database connection."""
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

with patch.dict(os.environ, {"ATTRIBUTION_DATABASE_URL": "postgresql+psycopg://unused:unused@127.0.0.1/unused"}):
    from app.access import identity
    from app.config import Settings
    from app.db import AuditEvent, LoginSession
    from app.modules.identity.api import Credentials, login, logout, me, router
    from app.security import password_hash, token_hash


class FakeDatabase:
    def __init__(self):
        self.user = SimpleNamespace(id="user-1", username="analyst", role="analyst",
                                    domains=["ecommerce"], active=True,
                                    password_hash=password_hash("test-password"))
        self.attempts = 0
        self.records = []
        self.sessions = {}
        self.commits = 0

    def scalar(self, statement):
        return self.attempts if "count(" in str(statement) else self.user

    def add(self, record):
        self.records.append(record)
        if isinstance(record, LoginSession):
            self.sessions[record.token_hash] = record

    def get(self, model, key):
        if model is LoginSession:
            return self.sessions.get(key)
        return self.user if key == self.user.id else None

    def delete(self, record):
        del self.sessions[record.token_hash]

    def commit(self):
        self.commits += 1


def request(method, cookie, csrf=None):
    headers = [(b"cookie", f"attribution_session={cookie}".encode())]
    if csrf:
        headers.append((b"x-csrf-token", csrf.encode()))
    return Request({"type": "http", "method": method, "path": "/", "headers": headers})


def test_login_me_csrf_and_logout():
    db, response = FakeDatabase(), Response()
    config = Settings(database_url="unused", session_hours=8, secure_cookie=True)
    with patch("app.modules.identity.api.settings", return_value=config):
        result = login(Credentials(username="analyst", password="test-password"), response, db)
    cookie_header = response.headers["set-cookie"]
    assert all(flag in cookie_header.lower() for flag in ("httponly", "secure", "samesite=strict"))
    cookie = cookie_header.split(";", 1)[0].split("=", 1)[1]
    assert token_hash(cookie) in db.sessions
    get_request = request("GET", cookie)
    user = identity(get_request, db)
    assert me(get_request, user)["username"] == "analyst"
    with pytest.raises(HTTPException) as failure:
        identity(request("POST", cookie), db)
    assert failure.value.status_code == 403
    logout_request = request("POST", cookie, result["csrf"])
    user = identity(logout_request, db)
    logout(logout_request, Response(), db, user)
    with pytest.raises(HTTPException) as failure:
        identity(request("GET", cookie), db)
    assert failure.value.status_code == 401
    assert any(isinstance(r, AuditEvent) and r.details["success"] for r in db.records)
    assert db.commits == 2


def test_failed_login_and_rate_limit():
    db = FakeDatabase()
    with pytest.raises(HTTPException) as failure:
        login(Credentials(username="analyst", password="wrong"), Response(), db)
    assert failure.value.status_code == 401
    assert not db.sessions
    assert db.records[0].details == {"success": False}
    assert db.commits == 1
    db.attempts = 10
    with pytest.raises(HTTPException) as failure:
        login(Credentials(username="analyst", password="test-password"), Response(), db)
    assert failure.value.status_code == 429
    assert db.commits == 1


def test_identity_locks_and_refreshes_user_authorization():
    from sqlalchemy.dialects import postgresql
    db, response = FakeDatabase(), Response()
    with patch('app.modules.identity.api.settings',return_value=Settings(database_url='unused',secure_cookie=False)):
        login(Credentials(username='analyst',password='test-password'),response,db)
    cookie=response.headers['set-cookie'].split(';',1)[0].split('=',1)[1]
    with patch.object(db,'scalar',wraps=db.scalar) as scalar:
        assert identity(request('GET',cookie),db) is db.user
        statement=scalar.call_args.args[0]
        assert 'FOR SHARE' in str(statement.compile(dialect=postgresql.dialect()))
        assert statement.get_execution_options().get('populate_existing') is True
    db.user.active=False
    with pytest.raises(HTTPException) as revoked:
        identity(request('GET',cookie),db)
    assert revoked.value.status_code==401


def test_identity_routes_registered_once():
    from app.main import app
    paths = app.openapi()["paths"]
    for path, method in (("/api/v1/auth/login", "POST"), ("/api/v1/me", "GET"), ("/api/v1/auth/logout", "POST")):
        assert method.lower() in paths[path]
        matches = [route for route in router.routes if route.path == path and method in route.methods]
        assert len(matches) == 1
