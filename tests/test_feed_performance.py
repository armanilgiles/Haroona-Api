import unittest
from contextlib import contextmanager

from fastapi import Request, Response
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Brand, City, Country, Product
from app.routers.feed import get_feed_filters, get_feed_products


def _request(*, if_none_match: str | None = None) -> Request:
    headers = []
    if if_none_match:
        headers.append((b"if-none-match", if_none_match.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/feed/filters",
            "raw_path": b"/feed/filters",
            "query_string": b"",
            "headers": headers,
            "client": ("test", 50000),
            "server": ("testserver", 80),
        }
    )


class FeedQueryPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        country = Country(code="JP", name="Japan")
        tokyo = City(
            slug="tokyo",
            name="Tokyo",
            country=country,
            latitude=35.6762,
            longitude=139.6503,
        )
        paris = City(
            slug="paris",
            name="Paris",
            country=country,
            latitude=48.8566,
            longitude=2.3522,
        )
        brand = Brand(name="Haroona Test", country=country)
        self.db.add_all([country, tokyo, paris, brand])
        self.db.flush()
        self.db.add_all(
            [
                Product(
                    external_id="tokyo-dress",
                    source="shopify",
                    name="Tokyo Linen Dress",
                    currency="USD",
                    brand_id=brand.id,
                    city_id=tokyo.id,
                    category="dress",
                    style="Minimal",
                    vibe="Summer",
                    city_connection_type="city_inspired_pick",
                    is_active=True,
                ),
                Product(
                    external_id="tokyo-sneaker",
                    source="shopify",
                    name="Tokyo Street Sneaker",
                    currency="USD",
                    brand_id=brand.id,
                    city_id=tokyo.id,
                    category="shoes",
                    style="Streetwear",
                    vibe="Urban",
                    city_connection_type="city_based_brand",
                    is_active=True,
                ),
                Product(
                    external_id="paris-bag",
                    source="shopify",
                    name="Paris Leather Bag",
                    currency="EUR",
                    brand_id=brand.id,
                    city_id=paris.id,
                    category="bag",
                    style="Classic",
                    vibe="Quiet Luxury",
                    city_connection_type="local_boutique",
                    is_active=True,
                ),
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

    def test_feed_page_uses_count_and_page_queries_without_relationship_n_plus_one(self):
        with self._select_statements() as statements:
            result = get_feed_products(
                city=None,
                cities=None,
                city_slugs=None,
                mode="lock",
                category=None,
                categories=None,
                style=None,
                vibe=None,
                city_connection_type=None,
                q=None,
                brand_id=None,
                per_city_limit=None,
                limit=24,
                offset=0,
                db=self.db,
            )

        self.assertEqual(result.total, 3)
        self.assertEqual(len(result.items), 3)
        self.assertEqual(len(statements), 2)

    def test_filter_metadata_is_scoped_and_uses_one_query(self):
        response = Response()
        with self._select_statements() as statements:
            result = get_feed_filters(
                request=_request(),
                response=response,
                city="tokyo",
                cities=None,
                city_slugs=None,
                city_connection_type=None,
                db=self.db,
            )

        groups = {group.key: group for group in result.categoryGroups}
        self.assertEqual(result.categories, ["dress", "shoes"])
        self.assertEqual(groups["dresses"].count, 1)
        self.assertEqual(groups["shoes"].count, 1)
        self.assertNotIn("bags", groups)
        self.assertEqual(len(statements), 1)
        self.assertEqual(
            response.headers["cache-control"],
            "public, max-age=60, must-revalidate",
        )
        self.assertTrue(response.headers["etag"].startswith('"'))

    def test_filter_metadata_honors_matching_etag(self):
        initial_response = Response()
        get_feed_filters(
            request=_request(),
            response=initial_response,
            city="tokyo",
            cities=None,
            city_slugs=None,
            city_connection_type=None,
            db=self.db,
        )

        result = get_feed_filters(
            request=_request(if_none_match=initial_response.headers["etag"]),
            response=Response(),
            city="tokyo",
            cities=None,
            city_slugs=None,
            city_connection_type=None,
            db=self.db,
        )

        self.assertIsInstance(result, Response)
        self.assertEqual(result.status_code, 304)
        self.assertEqual(result.headers["etag"], initial_response.headers["etag"])

    def test_filter_etag_changes_after_catalog_metadata_changes(self):
        initial_response = Response()
        get_feed_filters(
            request=_request(),
            response=initial_response,
            city="tokyo",
            cities=None,
            city_slugs=None,
            city_connection_type=None,
            db=self.db,
        )

        brand = self.db.query(Brand).first()
        tokyo = self.db.query(City).filter(City.slug == "tokyo").one()
        self.db.add(
            Product(
                external_id="tokyo-bag",
                source="shopify",
                name="Tokyo Mini Bag",
                currency="USD",
                brand_id=brand.id,
                city_id=tokyo.id,
                category="bag",
                style="Minimal",
                vibe="Urban",
                city_connection_type="city_inspired_pick",
                is_active=True,
            )
        )
        self.db.commit()

        changed_response = Response()
        result = get_feed_filters(
            request=_request(if_none_match=initial_response.headers["etag"]),
            response=changed_response,
            city="tokyo",
            cities=None,
            city_slugs=None,
            city_connection_type=None,
            db=self.db,
        )

        self.assertNotIsInstance(result, Response)
        self.assertNotEqual(
            changed_response.headers["etag"],
            initial_response.headers["etag"],
        )
        self.assertIn("bags", {group.key for group in result.categoryGroups})


if __name__ == "__main__":
    unittest.main()
