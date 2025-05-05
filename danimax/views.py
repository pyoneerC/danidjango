from django.http import Http404
from django.shortcuts import render

from danimax.models import Product


def index(request, product_id):
    try:
        products = Product.objects.all().order_by('-scraped_at')[:5]
    except Product.DoesNotExist:
        raise Http404("Product does not exist")
    context = {"products": products}
    return render(request, "danimax/detail.html", context)