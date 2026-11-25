"""Requires migrated PostgreSQL; intentionally separate from local pure tests."""
import secrets
import unittest
from integration_guard import check_target
check_target()
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from starlette.requests import Request
from app.main import app
from app.db import SessionFactory, User, LoginSession, AnalysisSession, AuditEvent, DatasetVersion, AnalysisRun, RunEvent, ModelCall, BusinessEvent, ReportArchive, MetricDraft
from app.security import password_hash
from app.config import settings
from app.access import COOKIE, identity


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.password = secrets.token_urlsafe(24)
        self.username = "test_" + secrets.token_hex(6)
        with SessionFactory() as db:
            self.user = User(username=self.username, password_hash=password_hash(self.password), role="analyst", domains=["ecommerce"])
            self.other = User(username=self.username + "_other", password_hash=self.user.password_hash, role="analyst", domains=["ecommerce"])
            self.viewer = User(username=self.username + "_viewer", password_hash=self.user.password_hash, role="manager", domains=["ecommerce"])
            db.add_all([self.user, self.other, self.viewer]); db.commit()
        self.client = TestClient(app, base_url=settings().public_origin)
        self.client.headers["origin"] = settings().public_origin
        self.authenticate(self.user.username)

    def authenticate(self, username):
        response = self.client.post("/api/v1/auth/login", json={"username":username, "password":self.password})
        self.assertEqual(response.status_code, 200)
        self.client.headers["x-csrf-token"] = response.json()["csrf"]

    def tearDown(self):
        self.client.close()
        ids = [self.user.id, self.other.id, self.viewer.id]
        with SessionFactory() as db:
            run_ids=select(AnalysisRun.id).where(AnalysisRun.owner_id.in_(ids))
            db.execute(delete(RunEvent).where(RunEvent.run_id.in_(run_ids)))
            db.execute(delete(ModelCall).where(ModelCall.run_id.in_(run_ids)))
            db.execute(delete(AnalysisRun).where(AnalysisRun.owner_id.in_(ids)))
            db.execute(delete(ReportArchive).where(ReportArchive.session_id.in_(
                select(AnalysisSession.id).where(AnalysisSession.owner_id.in_(ids)))))
            db.execute(delete(AnalysisSession).where(AnalysisSession.owner_id.in_(ids)))
            db.execute(delete(DatasetVersion).where(DatasetVersion.owner_id.in_(ids)))
            db.execute(delete(BusinessEvent).where(BusinessEvent.owner_id.in_(ids)))
            db.execute(delete(MetricDraft).where(MetricDraft.author_id.in_(ids)))
            db.execute(delete(LoginSession).where(LoginSession.user_id.in_(ids)))
            db.execute(delete(AuditEvent).where(AuditEvent.actor_id.in_(ids)))
            db.execute(delete(User).where(User.id.in_(ids))); db.commit()

    def create_analysis(self):
        response = self.client.post("/api/v1/sessions", json={"scenario":"ecommerce"})
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def test_archive_can_be_created_and_exported(self):
        identifier = self.create_analysis()
        from app.modules.analysis.snapshot import report_revision
        with SessionFactory() as db:
            revision = report_revision(db.get(AnalysisSession, identifier).snapshot)
        response = self.client.post(f'/api/v1/sessions/{identifier}/reports', json={'revision': revision})
        self.assertEqual(response.status_code, 201, response.text)
        report_id = response.json()['id']
        self.assertEqual(self.client.get(f'/api/v1/reports/{report_id}/export/md').status_code, 200)
        self.authenticate(self.other.username)
        self.assertEqual(self.client.get(f'/api/v1/reports/{report_id}/export/md').status_code, 404)

    def test_scope_is_server_enforced(self):
        response = self.client.get("/api/v1/dashboard")
        self.assertEqual([r["scenario_id"] for r in response.json()], ["ecommerce"])
        self.assertEqual(self.client.post("/api/v1/sessions", json={"scenario":"consumer"}).status_code, 403)

    def test_private_session_and_export(self):
        identifier = self.create_analysis()
        self.authenticate(self.other.username)
        for suffix in ("", "/report.md"):
            self.assertEqual(self.client.get(f"/api/v1/sessions/{identifier}{suffix}").status_code, 404)

    def test_csrf_origin_and_readonly_role(self):
        self.client.headers["x-csrf-token"] = "wrong"
        self.assertEqual(self.client.post("/api/v1/sessions", json={"scenario":"ecommerce"}).status_code,403)
        self.authenticate(self.viewer.username)
        self.assertEqual(self.client.post("/api/v1/sessions", json={"scenario":"ecommerce"}).status_code,403)
        self.client.headers["origin"] = "https://untrusted.invalid"
        self.assertEqual(self.client.post("/api/v1/auth/logout").status_code,403)

    def test_simulation_and_invalid_input(self):
        identifier = self.create_analysis()
        response = self.client.post(f"/api/v1/sessions/{identifier}/simulate", json={"changes":{"conversion":"0.035"}})
        self.assertEqual(response.status_code,200)
        self.assertEqual(float(response.json()["improvement"]),108000)
        self.assertEqual(self.client.post(f"/api/v1/sessions/{identifier}/simulate", json={"changes":{"conversion":"NaN"}}).status_code,422)
        report = self.client.get(f"/api/v1/sessions/{identifier}/report.md")
        self.assertEqual(report.status_code,200)
        self.assertIn("未完成统计归因验证", report.text)

    def test_revoked_access_and_logout(self):
        identifier = self.create_analysis()
        with SessionFactory() as db:
            db.get(User,self.user.id).domains=[]; db.commit()
        self.assertEqual(self.client.get(f"/api/v1/sessions/{identifier}").status_code,403)
        self.assertEqual(self.client.post("/api/v1/auth/logout").status_code,204)
        self.assertEqual(self.client.get("/api/v1/me").status_code,401)

    def test_permission_update_waits_for_authorized_request_transaction(self):
        identifier=self.create_analysis()
        cookie=self.client.cookies.get(COOKIE)
        request=Request({'type':'http','method':'GET','path':'/',
                         'headers':[(b'cookie',f'{COOKIE}={cookie}'.encode())]})
        with SessionFactory.begin() as holder:
            self.assertEqual(identity(request,holder).id,self.user.id)
            with self.assertRaises(DBAPIError):
                with SessionFactory.begin() as contender:
                    contender.execute(text("SET LOCAL lock_timeout = '250ms'"))
                    contender.execute(update(User).where(User.id==self.user.id).values(domains=[]))
        with SessionFactory.begin() as db:
            db.get(User,self.user.id).domains=[]
        self.assertEqual(self.client.get(f'/api/v1/sessions/{identifier}').status_code,403)

    def test_admin_can_create_metric_draft_with_migrated_schema(self):
        from app.domain.metric_catalog import catalog
        with SessionFactory.begin() as db:
            db.get(User,self.user.id).role='admin'
        payload={'scenario':'ecommerce','name':'测试指标草稿','definitions':catalog('ecommerce')['definitions']}
        created=self.client.post('/api/v1/admin/metric-drafts',json=payload)
        self.assertEqual(created.status_code,201,created.text)
        self.assertEqual(created.json()['status'],'draft')
        stored=self.client.get('/api/v1/admin/metric-drafts/'+created.json()['id'])
        self.assertEqual(stored.status_code,200,stored.text)
        self.assertEqual(stored.json()['definitions'],payload['definitions'])
