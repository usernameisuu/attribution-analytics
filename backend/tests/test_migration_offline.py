import os
import subprocess
import sys
import unittest
from pathlib import Path


class MigrationOfflineTests(unittest.TestCase):
    def test_publication_and_comments_sql_preview(self):
        env={**os.environ,'ATTRIBUTION_DATABASE_URL':'postgresql+psycopg://unused:unused@offline.invalid/unused'}
        result=subprocess.run([sys.executable,'-m','alembic','upgrade','0005:0008','--sql'],
                              cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('CREATE TABLE report_publications',result.stdout)
        self.assertIn('CREATE TABLE report_comments',result.stdout)
        self.assertIn('ix_report_comments_report_created',result.stdout)
        self.assertIn('CREATE TABLE brief_subscriptions',result.stdout)
        self.assertIn('CREATE TABLE brief_issues',result.stdout)
        self.assertNotIn('unused:unused',result.stdout)

    def test_sql_preview_does_not_connect(self):
        env={**os.environ,'ATTRIBUTION_DATABASE_URL':'postgresql+psycopg://unused:unused@offline.invalid/unused'}
        result=subprocess.run([sys.executable,'-m','alembic','upgrade','0003:0004','--sql'],
                              cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('CREATE TABLE report_archives',result.stdout)
        self.assertIn('ix_report_archives_owner_session_created',result.stdout)
        self.assertNotIn('unused:unused',result.stdout)

    def test_metric_draft_migration_sql_preview_does_not_connect(self):
        env={**os.environ,'ATTRIBUTION_DATABASE_URL':'postgresql+psycopg://unused:unused@offline.invalid/unused'}
        result=subprocess.run([sys.executable,'-m','alembic','upgrade','0004:0005','--sql'],
                              cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('CREATE TABLE metric_drafts',result.stdout)
        self.assertIn('ix_metric_drafts_scenario_created',result.stdout)
        self.assertNotIn('unused:unused',result.stdout)
