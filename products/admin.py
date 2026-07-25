from django.contrib import admin
from .models import Category, Brand, Unit, Product, ProductVariant, ProductImage, ProductBarcode, ProductPrice


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_name')


class ProductPriceInline(admin.TabularInline):
    model = ProductPrice
    extra = 1


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


class ProductBarcodeInline(admin.TabularInline):
    model = ProductBarcode
    extra = 1


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'brand', 'stock', 'retail_price', 'expiry_date', 'status')
    list_filter = ('category', 'brand', 'status')
    search_fields = ('name', 'barcode', 'sku')
    inlines = [ProductPriceInline, ProductImageInline, ProductBarcodeInline, ProductVariantInline]
