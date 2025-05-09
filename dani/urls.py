from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import path, include
from django.views.decorators.cache import never_cache
from django_ratelimit.decorators import ratelimit

from danimax import views

class SecureAdminSite(admin.AdminSite):
    login_template = 'admin/custom_login.html'

    def get_urls(self):
        from django.urls import re_path
        urls = super().get_urls()

        urls.insert(0, re_path(r'^.*$', staff_member_required(
            ratelimit(key='ip', rate='5/m', method='POST')(
                super().get_urls()[0].callback
            )
        )))
        return urls


secure_admin = SecureAdminSite(name='secure_admin')

# Apply security decorators to admin login
admin.site.login = ratelimit(key='ip', rate='5/m')(never_cache(admin.site.login))

urlpatterns = [
    # Custom secure admin path (not the default /admin/)
    path('control-panel-7X9z/', include(secure_admin.urls)),

    # Your other paths
    path('', views.index, name='index'),
    path("<int:product_id>/", views.detail, name="detail"),

    # Security middleware
    path('security/', include('django_security_headers.urls')),
]

# Additional security measures
if not settings.DEBUG:
    urlpatterns += [
        # HTTP Security Headers
        path('security-headers/', include('django_secure_headers.urls')),
    ]

    # Only serve admin over HTTPS
    admin.site.admin_view = staff_member_required(
        requires_https=True
    )(admin.site.admin_view)

# Static files in development only
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)