import unittest
from unittest.mock import Mock, patch

from app.curation.storefront_discovery import (
    discover_storefront_products,
    extract_storefront_page,
)


class StorefrontDiscoveryTests(unittest.TestCase):
    def test_extracts_embedded_json_ld_product_and_same_store_links(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {
            "@type": "Product",
            "name": "Striped Cotton Polo Dress",
            "url": "/products/striped-polo-dress",
            "brand": {"name": "Example"},
            "image": ["https://shop.example.com/images/polo.jpg"],
            "offers": {
              "price": "189.00",
              "priceCurrency": "USD",
              "availability": "https://schema.org/InStock"
            }
          }
          </script>
        </head><body>
          <a href="/products/striped-polo-dress">Polo dress</a>
          <a href="https://outside.example/products/not-ours">External</a>
        </body></html>
        """

        result = extract_storefront_page(
            html,
            base_url="https://shop.example.com/collections/dresses",
        )

        self.assertEqual(len(result.products), 1)
        self.assertEqual(result.products[0]["title"], "Striped Cotton Polo Dress")
        self.assertEqual(result.products[0]["_currency"], "USD")
        self.assertEqual(
            result.product_links,
            ["https://shop.example.com/products/striped-polo-dress"],
        )

    @patch("app.curation.storefront_discovery.requests.get")
    def test_crawls_public_product_links_when_collection_json_is_not_embedded(
        self,
        mock_get,
    ):
        collection_response = Mock(status_code=200)
        collection_response.text = (
            '<a href="/products/city-dress">City dress</a>'
        )
        collection_response.raise_for_status.return_value = None

        product_json_response = Mock(status_code=200)
        product_json_response.json.return_value = {
            "id": 42,
            "title": "City Dress",
            "handle": "city-dress",
            "vendor": "Example",
            "product_type": "Dress",
            "variants": [{"id": 1, "price": 7900, "available": True}],
            "images": ["https://cdn.example.com/city-dress.jpg"],
        }
        mock_get.side_effect = [collection_response, product_json_response]

        result = discover_storefront_products(
            "https://shop.example.com/collections/dresses",
            headers={"User-Agent": "test"},
            timeout_seconds=5,
            max_products=25,
        )

        self.assertEqual(result.discovery_method, "product_page_crawl")
        self.assertEqual(len(result.products), 1)
        self.assertEqual(result.products[0]["variants"][0]["price"], "79.00")
        self.assertEqual(
            result.products[0]["_merchant_url"],
            "https://shop.example.com/products/city-dress",
        )


if __name__ == "__main__":
    unittest.main()
