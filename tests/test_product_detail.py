import unittest
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Brand, City, Country, Product, ProductCandidate
from app.routers.products import get_product_detail


class ProductDetailEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        country = Country(code="GB", name="United Kingdom")
        self.london = City(
            slug="london",
            name="London",
            country=country,
            latitude=51.5074,
            longitude=-0.1278,
        )
        self.copenhagen = City(
            slug="copenhagen",
            name="Copenhagen",
            country=country,
            latitude=55.6761,
            longitude=12.5683,
        )
        self.brand = Brand(
            name="MANGO",
            country=country,
            logo_url="https://cdn.example.com/mango-logo.png",
        )
        self.db.add_all([country, self.london, self.copenhagen, self.brand])
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _product(
        self,
        external_id: str = "coat-42",
        *,
        is_active: bool = True,
        include_optional_fields: bool = True,
    ) -> Product:
        product = Product(
            external_id=external_id,
            source="shopify",
            name="Tailored Wool Blend Coat",
            price=129.99 if include_optional_fields else None,
            regular_price=159.99 if include_optional_fields else None,
            currency="GBP",
            affiliate_url=(
                "https://tatrck.com/h/verified-coat"
                if include_optional_fields
                else None
            ),
            merchant_url=(
                "https://shop.example.com/products/coat-42"
                if include_optional_fields
                else None
            ),
            is_affiliate=include_optional_fields,
            product_image_url=(
                "https://cdn.example.com/coat.jpg"
                if include_optional_fields
                else None
            ),
            product_image_alt="Woman wearing a tailored wool coat",
            brand_id=self.brand.id,
            city_id=self.london.id,
            category="coat",
            style="Minimal",
            vibe="Timeless",
            is_active=is_active,
            availability_status="in_stock" if is_active else "archived",
            city_connection_type="city_inspired_pick",
            city_connection_location="London",
            city_connection_note="Structured tailoring suits London city life.",
        )
        self.db.add(product)
        self.db.flush()
        return product

    def _candidate(self, product: Product) -> ProductCandidate:
        candidate = ProductCandidate(
            source="shopify",
            source_type="single_product",
            source_url=product.merchant_url,
            merchant_name="MANGO",
            brand_name="MANGO",
            external_product_id=product.external_id,
            title=product.name,
            description="Structured tailoring with clean, classic proportions.",
            price_amount=product.price,
            currency=product.currency,
            affiliate_url=product.affiliate_url,
            merchant_url=product.merchant_url,
            affiliate_link_status="verified",
            affiliate_link_verified_at=datetime.now(timezone.utc),
            affiliate_link_verified_by="test-curator",
            availability="in_stock",
            normalized_category="coat",
            target_city_slug="london",
            city_fit_score=88,
            city_fit_scores={"london": 88, "copenhagen": 81},
            city_candidates=[
                {
                    "city_slug": "copenhagen",
                    "city_fit_score": 81,
                    "confidence": 86,
                    "match_type": "strong_multi_city_fit",
                    "primary_match_eligible": False,
                    "score_reasons": [
                        "Visual compatibility 8/10 (24/30)",
                        "Climate compatibility 8/10 (20/25)",
                        "Lifestyle compatibility 8/10 (16/20)",
                        "Distinctiveness 21/25",
                    ],
                    "scoring_analysis": {
                        "comparative_reason": "Clean lines also suit Copenhagen."
                    },
                },
                {
                    "city_slug": "london",
                    "city_fit_score": 88,
                    "confidence": 92,
                    "match_type": "distinctive_primary_match",
                    "primary_match_eligible": True,
                    "scoring_analysis": {
                        "comparative_reason": "Structured tailoring is strongest for London.",
                        "component_points": {
                            "visual_aesthetic": 27,
                            "climate_practicality": 22.5,
                            "lifestyle_occasion": 18,
                            "distinctive_enhancement": 20.5,
                        },
                        "component_max_points": {
                            "visual_aesthetic": 30,
                            "climate_practicality": 25,
                            "lifestyle_occasion": 20,
                            "distinctive_enhancement": 25,
                        },
                        "component_reasons": {
                            "visual_aesthetic": ["Structured silhouette aligns strongly."],
                        },
                    },
                },
            ],
            scoring_confidence=92,
            scoring_analysis={
                "recognized_concepts": ["Minimal", "Layered"],
                "observed_garment_details": [
                    "Wool blend fabric",
                    "Notched lapel collar",
                ],
            },
            manual_observed_garment_details=["Tailored fit"],
            haroona_score=88,
            score_reasons=[],
            review_status="approved",
            promoted_product_id=product.id,
        )
        self.db.add(candidate)
        self.db.commit()
        return candidate

    def test_success_serializes_real_city_analysis_in_score_order(self):
        product = self._product()
        self._candidate(product)

        detail = get_product_detail("coat-42", db=self.db)

        self.assertEqual(detail.productId, "coat-42")
        self.assertEqual(detail.dbProductId, product.id)
        self.assertEqual(detail.brandName, "MANGO")
        self.assertEqual(detail.price, "129.99")
        self.assertEqual(detail.originalPrice, "159.99")
        self.assertEqual(detail.description, "Structured tailoring with clean, classic proportions.")
        self.assertEqual(
            [item.cityName for item in detail.cityAnalysis],
            ["London", "Copenhagen"],
        )
        self.assertEqual([item.score for item in detail.cityAnalysis], [88, 81])
        self.assertEqual(detail.cityAnalysis[0].matchLabel, "Primary Match")
        self.assertEqual(detail.cityAnalysis[1].matchLabel, "Strong Multi-City Fit")
        self.assertEqual(
            [component.label for component in detail.cityAnalysis[0].scoreComponents],
            ["Visual", "Climate", "Lifestyle", "Distinctiveness"],
        )
        self.assertEqual(detail.cityAnalysis[0].scoreComponents[0].score, 27)
        self.assertEqual(detail.cityAnalysis[0].scoreComponents[0].maxScore, 30)
        self.assertEqual(
            detail.cityAnalysis[0].scoreComponents[0].reasons,
            ["Structured silhouette aligns strongly."],
        )
        self.assertEqual(detail.cityAnalysis[1].scoreComponents[0].score, 24)
        self.assertEqual(detail.cityAnalysis[1].scoreComponents[3].maxScore, 25)
        self.assertEqual(
            detail.details,
            ["Tailored fit", "Wool blend fabric", "Notched lapel collar"],
        )
        self.assertEqual(detail.styleTags, ["Minimal", "Timeless", "Layered"])

    def test_not_found_returns_404(self):
        with self.assertRaises(HTTPException) as raised:
            get_product_detail("missing-product", db=self.db)

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail["code"], "product_not_found")

    def test_archived_product_returns_410(self):
        product = self._product("archived-coat", is_active=False)
        self.db.commit()

        with self.assertRaises(HTTPException) as raised:
            get_product_detail(product.external_id, db=self.db)

        self.assertEqual(raised.exception.status_code, 410)
        self.assertEqual(raised.exception.detail["code"], "product_unavailable")

    def test_optional_missing_fields_degrade_to_empty_values(self):
        product = self._product("minimal-coat", include_optional_fields=False)
        self.db.commit()

        detail = get_product_detail(product.external_id, db=self.db)

        self.assertIsNone(detail.price)
        self.assertIsNone(detail.originalPrice)
        self.assertIsNone(detail.productImage)
        self.assertIsNone(detail.description)
        self.assertEqual(detail.details, [])
        self.assertEqual(detail.additionalImages, [])
        self.assertFalse(detail.merchantDestinationAvailable)
        self.assertEqual(len(detail.cityAnalysis), 1)
        self.assertIsNone(detail.cityAnalysis[0].score)

    def test_verified_affiliate_destination_remains_primary(self):
        product = self._product()
        self._candidate(product)

        detail = get_product_detail(product.external_id, db=self.db)

        self.assertTrue(detail.isAffiliate)
        self.assertEqual(detail.affiliateUrl, "https://tatrck.com/h/verified-coat")
        self.assertEqual(
            detail.merchantUrl,
            "https://shop.example.com/products/coat-42",
        )

    def test_optimized_image_preserves_original_merchant_fallback(self):
        product = self._product("optimized-coat")
        product.optimized_product_image_url = "https://cdn.example.com/optimized.webp"
        product.product_image_width = 640
        product.product_image_height = 960
        self.db.commit()

        detail = get_product_detail("optimized-coat", db=self.db)

        self.assertEqual(detail.productImage.url, "https://cdn.example.com/optimized.webp")
        self.assertEqual(detail.productImage.width, 640)
        self.assertEqual(detail.productImage.height, 960)
        self.assertEqual(
            detail.originalProductImage.url,
            "https://cdn.example.com/coat.jpg",
        )

    def test_detail_query_budget_avoids_relationship_and_identifier_n_plus_one(self):
        product = self._product("query-budget-coat")
        self._candidate(product)
        identifier = product.external_id
        statements: list[str] = []

        def record_statement(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            detail = get_product_detail(identifier, db=self.db)
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        self.assertEqual(detail.productId, identifier)
        self.assertEqual(len(statements), 3)


if __name__ == "__main__":
    unittest.main()
