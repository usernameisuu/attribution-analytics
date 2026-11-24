import unittest
from types import SimpleNamespace
from unittest.mock import patch
from integration_guard import validate_url, check_target


class IntegrationGuardTests(unittest.TestCase):
    def test_accepts_only_explicit_test_target(self):
        validate_url("postgresql+psycopg://attribution_test:pass@localhost:5432/attribution_test")

    def test_rejects_business_database_and_connection_overrides(self):
        for url in ("", "postgresql+psycopg://attribution:pass@localhost/attribution",
                    "postgresql+psycopg://attribution_test:pass@localhost/attribution",
                    "postgresql+psycopg://attribution:pass@localhost/attribution_test",
                    "postgresql+psycopg://attribution_test:pass@localhost/attribution_test?options=-crole%3Dother",
                    "postgresql+psycopg://attribution_test:pass@localhost:invalid/attribution_test"):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                validate_url(url)

    def test_requires_matching_explicit_environment_urls_before_connecting(self):
        test_url = "postgresql+psycopg://attribution_test:pass@localhost/attribution_test"
        for environment in ({}, {"ATTRIBUTION_TEST_DATABASE_URL": test_url},
                            {"ATTRIBUTION_TEST_DATABASE_URL": test_url,
                             "ATTRIBUTION_DATABASE_URL": "postgresql+psycopg://app:pass@localhost/app"}):
            with self.subTest(environment=environment), patch.dict("os.environ", environment, clear=True):
                with self.assertRaises(RuntimeError):
                    check_target()

    def test_connected_identity_must_match_and_engine_is_disposed(self):
        url = "postgresql+psycopg://attribution_test:pass@localhost/attribution_test"
        for actual, allowed in ((('attribution_test',) * 3, True),
                                (('business', 'attribution_test', 'attribution_test'), False),
                                (('attribution_test', 'admin', 'attribution_test'), False),
                                (('attribution_test', 'attribution_test', 'admin'), False)):
            with self.subTest(actual=actual):
                class Connection:
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def execute(self, statement): return SimpleNamespace(one=lambda: actual)

                class Engine:
                    disposed = False
                    def connect(self): return Connection()
                    def dispose(self): self.disposed = True

                engine = Engine()
                fake_sqlalchemy = SimpleNamespace(create_engine=lambda *args, **kwargs: engine,
                                                  text=lambda statement: statement)
                with patch.dict("os.environ", {"ATTRIBUTION_TEST_DATABASE_URL": url,
                                               "ATTRIBUTION_DATABASE_URL": url}, clear=True), \
                     patch.dict("sys.modules", {"sqlalchemy": fake_sqlalchemy}):
                    if allowed:
                        check_target()
                    else:
                        with self.assertRaises(RuntimeError): check_target()
                self.assertTrue(engine.disposed)
