import asyncio
import unittest

from fastapi import Request, Response
from sqlalchemy import create_engine, text

from app.performance import install_query_metrics, measure_request


class PerformanceMetricsTests(unittest.TestCase):
    def test_server_timing_reports_database_query_count(self):
        install_query_metrics()
        engine = create_engine("sqlite:///:memory:")
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "scheme": "http",
                "path": "/timed",
                "raw_path": b"/timed",
                "query_string": b"",
                "headers": [],
                "client": ("test", 50000),
                "server": ("testserver", 80),
            }
        )

        async def call_next(_request):
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return Response("ok")

        try:
            response = asyncio.run(measure_request(request, call_next))
        finally:
            engine.dispose()

        self.assertIn("app;dur=", response.headers["server-timing"])
        self.assertIn('desc="1 queries"', response.headers["server-timing"])


if __name__ == "__main__":
    unittest.main()
