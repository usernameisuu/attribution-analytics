"""HTTP origin checks without opening a database connection."""
import os
import json
import unittest
from unittest.mock import patch

from starlette.requests import Request
from starlette.responses import JSONResponse

with patch.dict(os.environ, {"ATTRIBUTION_DATABASE_URL": os.environ.get("ATTRIBUTION_DATABASE_URL", "postgresql+psycopg://unused:unused@127.0.0.1/unused")}):
    from app.main import request_boundary

from app.config import Settings, settings


class OriginBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.config = Settings(
            database_url="postgresql+psycopg://unused:unused@127.0.0.1/unused",
            public_origin="http://127.0.0.1:5173",
            additional_public_origins=["http://localhost:5173"],
        )
        self.override = patch("app.main.settings", return_value=self.config)
        self.override.start()
        self.addCleanup(self.override.stop)
        self.addCleanup(settings.cache_clear)

    def post(self, origin):
        headers = [] if origin is None else [(b"origin", origin.encode())]
        request = Request({"type": "http", "method": "POST", "path": "/probe", "headers": headers})

        async def next_handler(request):
            return JSONResponse({"ok": True})

        # The stub performs no I/O, so this coroutine must complete without
        # an event loop or a loopback socket. Fail if that ever changes.
        coroutine = request_boundary(request, next_handler)
        try:
            coroutine.send(None)
        except StopIteration as completed:
            return completed.value
        finally:
            coroutine.close()
        raise AssertionError("Origin boundary unexpectedly suspended")

    def test_both_configured_origins_pass(self):
        for origin in ("http://127.0.0.1:5173", "http://localhost:5173"):
            with self.subTest(origin=origin):
                self.assertEqual(self.post(origin).status_code, 200)

    def test_untrusted_or_missing_origin_is_rejected(self):
        for origin in (None, "null", "http://localhost:5174", "https://localhost:5173",
                       "http://localhost:5173.attacker.example", "http://attacker.example"):
            with self.subTest(origin=origin):
                response = self.post(origin)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(json.loads(response.body)["code"], "ORIGIN_REJECTED")

    def test_extra_origin_must_be_explicitly_enabled(self):
        self.config.additional_public_origins = []
        self.assertEqual(self.post("http://localhost:5173").status_code, 403)
        self.assertEqual(self.post(self.config.public_origin).status_code, 200)

    def test_environment_array_is_parsed(self):
        with patch.dict(os.environ, {"ATTRIBUTION_ADDITIONAL_PUBLIC_ORIGINS": '["http://localhost:5173"]'}):
            config = Settings(database_url="unused")
        self.assertEqual(config.additional_public_origins, ["http://localhost:5173"])


if __name__ == "__main__":
    unittest.main()
