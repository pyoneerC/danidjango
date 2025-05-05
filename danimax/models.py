from django.db import models

# Create your models here.
class Product(models.Model):
    url = models.URLField(max_length=100, unique=True)
    name = models.CharField(max_length=100)
    price_ars = models.FloatField()
    image_url = models.URLField(max_length=100)
    scraped_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.price_ars} ARS"

    def get_price(self):
        return f"${self.price_ars:,.2f}"

    def get_image_url(self):
        return self.image_url if self.image_url else "https://via.placeholder.com/150"

    def get_scraped_at(self):
        return self.scraped_at.strftime("%Y-%m-%d %H:%M:%S")

    def get_url(self):
        return self.url if self.url else "https://example.com"

    class Meta:
        ordering = ['-scraped_at']
        verbose_name = 'Product'
        verbose_name_plural = 'Products'