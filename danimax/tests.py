from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Product


class ProductModelTest(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            url="http://example.com/product/1",
            name="Test Product",
            price_ars=100.0,
            image_url="http://example.com/image.jpg"
        )

    def test_product_creation(self):
        self.assertEqual(self.product.name, "Test Product")
        self.assertEqual(self.product.price_ars, 100.0)
        self.assertEqual(self.product.image_url, "http://example.com/image.jpg")

    def test_get_price_formatting(self):
        self.assertEqual(self.product.get_price(), "$100.00")

    def test_get_url(self):
        self.assertEqual(self.product.get_url(), "http://example.com/product/1")

    def test_get_image_url(self):
        self.assertEqual(self.product.get_image_url(), "http://example.com/image.jpg")

    def test_get_scraped_at(self):
        self.assertIsNotNone(self.product.get_scraped_at())


    def test_price_rounding(self):
        self.product.price_ars = 199.999
        self.product.save()
        self.assertEqual(self.product.get_price(), "$200.00")

    def test_url_must_be_valid(self):
        with self.assertRaises(ValidationError):
            invalid = Product(
                url="not-a-url",
                name="Invalid Product",
                price_ars=100.0
            )
            invalid.full_clean()

    def test_negative_price_should_fail(self):
        with self.assertRaises(ValidationError):
            p = Product(name="Freebie", url="http://test.com", price_ars=-50)
            p.full_clean()

    def test_ordering_by_price(self):
        Product.objects.create(
            url="http://example.com/product/2",
            name="Cheaper Product",
            price_ars=50.0
        )
        cheapest = Product.objects.order_by('price_ars').first()
        self.assertEqual(cheapest.name, "Cheaper Product")

    def test_bulk_create_and_query_efficiency(self):
        Product.objects.bulk_create([
            Product(url=f"http://example.com/{i}", name=f"Product {i}", price_ars=i)
            for i in range(100)
        ])
        self.assertEqual(Product.objects.count(), 101)  # 100 + 1 from setUp

    def test_unicode_handling_in_name(self):
        unicode_product = Product.objects.create(
            url="http://example.com/unicode",
            name="Ñandú 🦤 Piñata",
            price_ars=77.0
        )
        self.assertIn("Ñandú", unicode_product.name)
        self.assertIn("🦤", unicode_product.name)

    def test_duplicate_url_constraint(self):
        with self.assertRaises(Exception):
            Product.objects.create(
                url="http://example.com/product/1",  # same as self.product
                name="Dup Product",
                price_ars=100.0
            )
