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

    def test_extracts_next_data_and_headless_goods_links(self):
        html = """
        <html><head>
          <script id="__NEXT_DATA__" type="application/json">
          {
            "props": {"pageProps": {"product": {
              "name": "Pleated City Skirt",
              "productUrl": "/us/goods/1023791",
              "image": "/images/skirt.jpg",
              "offers": {"price": "98.00", "priceCurrency": "USD"}
            }}}
          }
          </script>
        </head><body>
          <a href="/us/goods/1023791">Pleated City Skirt</a>
        </body></html>
        """

        result = extract_storefront_page(
            html,
            base_url=(
                "https://global.example.com/us/category/100?"
                "category1DepthCode=100&gender=F"
            ),
        )

        self.assertEqual(len(result.products), 1)
        self.assertEqual(result.products[0]["title"], "Pleated City Skirt")
        self.assertEqual(
            result.product_links,
            ["https://global.example.com/us/goods/1023791"],
        )

    def test_extracts_json_from_inline_initial_state_assignment(self):
        html = """
        <script>
          window.__INITIAL_STATE__ = {
            "catalog": {"items": [{
              "name": "Relaxed Linen Dress",
              "product_url": "/item/linen-dress",
              "image": "/images/linen-dress.jpg",
              "offers": {"price": "120.00", "priceCurrency": "USD"}
            }]}
          };
        </script>
        """

        result = extract_storefront_page(
            html,
            base_url="https://shop.example.com/women/dresses",
        )

        self.assertEqual(len(result.products), 1)
        self.assertEqual(result.products[0]["title"], "Relaxed Linen Dress")
        self.assertEqual(
            result.product_links,
            ["https://shop.example.com/item/linen-dress"],
        )

    def test_recognizes_nested_product_card_links_without_accepting_navigation(self):
        html = """
        <a class="product-card" href="/us/en-us/women/trousers/outdoor-trousers/stina-trousers-w/">
          Stina Trousers W
        </a>
        <a href="/us/en-us/women/trousers/outdoor-trousers/contact">Contact</a>
        <a href="/us/en-us/women/jackets/">Jackets</a>
        """

        result = extract_storefront_page(
            html,
            base_url=(
                "https://www.example.com/us/en-us/women/trousers/"
                "outdoor-trousers/"
            ),
        )

        self.assertEqual(
            result.product_links,
            [
                "https://www.example.com/us/en-us/women/trousers/"
                "outdoor-trousers/stina-trousers-w/"
            ],
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

    @patch("app.curation.storefront_discovery.requests.get")
    def test_crawls_goods_product_pages_and_preserves_source_query(self, mock_get):
        collection_response = Mock(status_code=200)
        collection_response.text = '<a href="/us/goods/1023791">City skirt</a>'
        collection_response.raise_for_status.return_value = None

        product_response = Mock(status_code=200)
        product_response.text = """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "City Skirt",
          "url": "/us/goods/1023791",
          "image": ["/images/city-skirt.jpg"],
          "offers": {
            "price": "98.00",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
        """
        product_response.raise_for_status.return_value = None
        mock_get.side_effect = [collection_response, product_response]
        source_url = (
            "https://global.example.com/us/category/100?"
            "category1DepthCode=100&gender=F"
        )

        result = discover_storefront_products(
            source_url,
            headers={"User-Agent": "test"},
            timeout_seconds=5,
            max_products=25,
        )

        self.assertEqual(mock_get.call_args_list[0].args[0], source_url)
        self.assertEqual(result.discovery_method, "product_page_crawl")
        self.assertEqual(result.products[0]["title"], "City Skirt")
        self.assertEqual(
            result.products[0]["_merchant_url"],
            "https://global.example.com/us/goods/1023791",
        )


if __name__ == "__main__":
    unittest.main()
