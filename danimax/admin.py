from django.contrib import admin
from django.utils.html import format_html

from .models import Product

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price_ars', 'short_url', 'scraped_at', 'preview_image')
    list_filter = ('scraped_at',)
    search_fields = ('name', 'url')
    ordering = ('-scraped_at',)
    readonly_fields = ('scraped_at',)
    actions = ['mark_price_zero']

    def short_url(self, obj):
        return obj.url[:40] + '...' if len(obj.url) > 40 else obj.url
    short_url.short_description = 'URL'

    def preview_image(self, obj):
        return f'<img src="{obj.image_url}" width="60" />'
    preview_image.short_description = 'Image'
    preview_image.allow_tags = True

    def mark_price_zero(self, queryset):
        queryset.update(price_ars=0)
    mark_price_zero.short_description = 'Set selected prices to 0'

    def preview_image(self, obj):
        return format_html('<img src="{}" width="60" />', obj.image_url)
