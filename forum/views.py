from django.shortcuts import render, get_object_or_404
from .models import Category, SubCategory

def forum_view(request):
    categories = Category.objects.all()
    subcategories = SubCategory.objects.all()

    context = {
            'categories': categories,
            'subcategories': subcategories,
            }

    return render(request, 'forum/forum_index.html', context)

def subcategory_detail(request, slug):
    subcategory = get_object_or_404(SubCategory, slug=slug)
    context = {'subcategory': subcategory}
    return render(request, 'forum/subcategory_detail.html', context)
