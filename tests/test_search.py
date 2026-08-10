import unittest

from fastapi import Response
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Brand, City, Country, Product
from app.routers.search import MINIMUM_QUERY_LENGTH, search_catalog


class SearchEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        japan = Country(code="JP", name="Japan")
        united_kingdom = Country(code="GB", name="United Kingdom")
        united_states = Country(code="US", name="United States")

        self.tokyo = City(
            slug="tokyo",
            name="Tokyo",
            country=japan,
            latitude=35.6762,
            longitude=139.6503,
        )
        self.london = City(
            slug="london",
            name="London",
            country=united_kingdom,
            latitude=51.5074,
            longitude=-0.1278,
        )
        self.new_york = City(
            slug="new-york",
            name="New York",
            country=united_states,
            latitude=40.7128,
            longitude=-74.0060,
        )

        mango = Brand(name="MANGO", country=united_kingdom)
        reformation = Brand(name="Reformation", country=united_states)
        archive_only = Brand(name="Archive Brand", country=united_states)

        self.db.add_all(
            [
                japan,
                united_kingdom,
                united_states,
                self.tokyo,
                self.london,
                self.new_york,
                mango,
                reformation,
                archive_only,
            ]
        )
        self.db.flush()

        self.db.add_all(
            [
                self._product(
                    external_id="mango-white-cami",
                    name="White Linen Camisole",
                    brand=mango,
                    city=self.tokyo,
                    category="tops",
                    style="Quiet Luxury",
                    vibe="Minimal",
                ),
                self._product(
                    external_id="reformation-linen-midi",
                    name="Linen Midi Dress",
                    brand=reformation,
                    city=self.london,
                    category="dresses",
                    style="Coastal",
                    vibe="Romantic",
                ),
                self._product(
                    external_id="reformation-silk-mini",
                    name="Silk Mini Dress",
                    brand=reformation,
                    city=self.new_york,
                    category="dresses",
                    style="Night Out",
                    vibe="Minimal",
                ),
                self._product(
                    external_id="archive-only-product",
                    name="Archived Linen Dress",
                    brand=archive_only,
                    city=self.london,
                    category="dresses",
                    style="Quiet Luxury",
                    vibe="Minimal",
                    is_active=False,
                ),
                self._product(
                    external_id="unpublished-awin-product",
                    name="Unpublished Linen Dress",
                    brand=archive_only,
                    city=self.london,
                    category="dresses",
                    style="Quiet Luxury",
                    vibe="Minimal",
                    source="awin",
                ),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    @staticmethod
    def _product(
        *,
        external_id: str,
        name: str,
        brand: Brand,
        city: City,
        category: str,
        style: str,
        vibe: str,
        is_active: bool = True,
        source: str = "shopify",
    ) -> Product:
        return Product(
            external_id=external_id,
            source=source,
            name=name,
            currency="USD",
            affiliate_url="https://example.com/product",
            brand=brand,
            city=city,
            category=category,
            style=style,
            vibe=vibe,
            is_active=is_active,
        )

    def _search(self, query: str, *, limit: int = 6):
        response = Response()
        result = search_catalog(response=response, q=query, limit=limit, db=self.db)
        self.assertEqual(
            response.headers["cache-control"],
            "public, max-age=30, stale-while-revalidate=60",
        )
        return result

    def test_linen_returns_lightweight_products_and_excludes_unpublished_rows(self):
        result = self._search("linen")

        self.assertEqual(
            {product.productName for product in result.products},
            {"White Linen Camisole", "Linen Midi Dress"},
        )
        self.assertNotIn("Archived Linen Dress", [item.productName for item in result.products])
        self.assertNotIn("Unpublished Linen Dress", [item.productName for item in result.products])
        self.assertEqual(result.products[0].model_fields_set, {
            "productId",
            "dbProductId",
            "productName",
            "brandName",
            "category",
            "style",
            "vibe",
            "citySlug",
            "cityName",
        })

    def test_multi_term_white_top_can_match_across_name_and_category(self):
        result = self._search("white top")

        self.assertEqual([item.productName for item in result.products], ["White Linen Camisole"])

    def test_city_name_is_searched_directly(self):
        result = self._search("Tokyo")

        self.assertEqual([city.name for city in result.cities], ["Tokyo"])
        self.assertEqual(result.cities[0].countryCode, "JP")
        self.assertEqual([item.cityName for item in result.products], ["Tokyo"])

    def test_multi_word_city_name_is_supported(self):
        result = self._search("New York")

        self.assertEqual([city.slug for city in result.cities], ["new-york"])

    def test_brand_search_only_returns_brands_in_the_curated_catalog(self):
        mango = self._search("Mango")
        archive = self._search("Archive Brand")

        self.assertEqual([brand.name for brand in mango.brands], ["MANGO"])
        self.assertEqual(archive.brands, [])

    def test_categories_and_styles_come_from_database_values(self):
        category_result = self._search("dress")
        style_result = self._search("quiet luxury")

        self.assertEqual(
            [(item.value, item.label, item.kind) for item in category_result.categories],
            [("dresses", "Dresses", "category")],
        )
        self.assertEqual(
            [(item.value, item.kind) for item in style_result.styles],
            [("Quiet Luxury", "style")],
        )

    def test_nonexistent_query_returns_empty_groups(self):
        result = self._search("nonexistent-query")

        self.assertEqual(result.cities, [])
        self.assertEqual(result.categories, [])
        self.assertEqual(result.brands, [])
        self.assertEqual(result.styles, [])
        self.assertEqual(result.products, [])

    def test_empty_and_one_character_queries_do_not_hit_database(self):
        statements = []

        def record_statement(*args):
            statements.append(args[2])

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            empty = self._search("   ")
            one_character = self._search("x")
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        self.assertEqual(empty.query, "")
        self.assertEqual(empty.minimumQueryLength, MINIMUM_QUERY_LENGTH)
        self.assertEqual(one_character.products, [])
        self.assertEqual(statements, [])

    def test_sql_wildcards_are_treated_as_literal_special_characters(self):
        result = self._search("%_")

        self.assertEqual(result.cities, [])
        self.assertEqual(result.categories, [])
        self.assertEqual(result.brands, [])
        self.assertEqual(result.styles, [])
        self.assertEqual(result.products, [])

    def test_per_group_limit_uses_has_more_without_count_queries(self):
        result = self._search("dress", limit=1)

        self.assertEqual(len(result.products), 1)
        self.assertTrue(result.hasMore.products)

    def test_grouped_search_uses_a_fixed_number_of_queries_without_n_plus_one(self):
        statements = []

        def record_statement(*args):
            statements.append(args[2])

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            result = self._search("linen")
            serialized = result.model_dump()
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        self.assertEqual(len(statements), 5)
        self.assertTrue(all(statement.lstrip().upper().startswith("SELECT") for statement in statements))
        self.assertEqual(len(serialized["products"]), 2)


if __name__ == "__main__":
    unittest.main()
