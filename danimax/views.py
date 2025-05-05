from django.http import Http404
from django.shortcuts import render

from danimax.models import Product


def index(request):
    products = Product.objects.all()
    context = {"products": products}
    return render(request, "danimax/index.html", context)

def detail(request, product_id):
    try:
        product = Product.objects.get(id=product_id)
    except Product.DoesNotExist:
        raise Http404("Product does not exist")
    context = {"product": product}
    return render(request, "danimax/detail.html", context)