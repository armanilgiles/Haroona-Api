import unittest
from contextlib import contextmanager

from fastapi import Request, Response
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Brand, City, Country
from app.routers.brands import get_brands
from app.routers.cities import get_cities
from app.routers.countries import get_countries


def _request(path: str) -> Request:
    encoded_path = path.encode("ascii")
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": encoded_path,
            "query_string": b"",
            "headers": [],
            "client": ("test", 50000),
            "server": ("testserver", 80),
        }
    )


class ReferenceEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        country = Country(code="FR", name="France")
        self.db.add_all(
            [
                country,
                City(
                    slug="paris",
                    name="Paris",
                    country=country,
                    latitude=48.8566,
                    longitude=2.3522,
                ),
                Brand(name="Haroona Test", country=country),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    @contextmanager
    def _select_statements(self):
        statements: list[str] = []

        def record_statement(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            yield statements
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

    def test_reference_lists_serialize_with_one_query_each_and_cache_headers(self):
        responses = [Response(), Response(), Response()]
        with self._select_statements() as statements:
            countries = get_countries(
                request=_request("/countries"),
                response=responses[0],
                db=self.db,
            )
            brands = get_brands(
                request=_request("/brands"),
                response=responses[1],
                country=None,
                db=self.db,
            )
            cities = get_cities(
                request=_request("/cities"),
                response=responses[2],
                country_code=None,
                db=self.db,
            )

        self.assertEqual(countries[0].code, "FR")
        self.assertEqual(brands[0].country.code, "FR")
        self.assertEqual(cities[0].countryCode, "FR")
        self.assertEqual(len(statements), 3)
        for response in responses:
            self.assertEqual(
                response.headers["cache-control"],
                "public, max-age=60, must-revalidate",
            )
            self.assertTrue(response.headers["etag"])


if __name__ == "__main__":
    unittest.main()
