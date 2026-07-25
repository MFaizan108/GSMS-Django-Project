from decimal import Decimal

from django.db import models
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Unit(models.Model):
    name = models.CharField(max_length=50, unique=True)  # e.g. Piece, Packet, Kg
    short_name = models.CharField(max_length=10, blank=True)  # e.g. pcs, kg

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        INACTIVE = 'inactive', 'Inactive'
        DISCONTINUED = 'discontinued', 'Discontinued'

    name = models.CharField(max_length=200)
    barcode = models.CharField(max_length=64, unique=True, blank=True, null=True)
    sku = models.CharField(max_length=64, unique=True, blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='products')
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, related_name='products')
    tax = models.ForeignKey('masters.Tax', on_delete=models.SET_NULL, null=True, blank=True, related_name='products')

    # Default/last-known cost for new-item convenience only — actual COGS at
    # sale time comes from ProductBatch.unit_cost via FIFO allocation.
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Cached total across all warehouses/batches — maintained only by
    # inventory.services, never editable via forms/admin.
    stock = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    minimum_stock = models.DecimalField(max_digits=12, decimal_places=2, default=5)

    expiry_date = models.DateField(null=True, blank=True)
    manufacture_date = models.DateField(null=True, blank=True)

    image = models.ImageField(upload_to='products/', null=True, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('products:product_detail', args=[self.pk])

    @property
    def is_low_stock(self):
        return self.stock <= self.minimum_stock

    @property
    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < timezone.localdate())

    @property
    def is_near_expiry(self):
        if not self.expiry_date:
            return False
        today = timezone.localdate()
        return today <= self.expiry_date <= today + timedelta(days=30)

    @property
    def days_to_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - timezone.localdate()).days

    @property
    def retail_price(self):
        """Default selling price shown in the POS / product list — the
        product's price at the default PriceLevel (Retail), or whichever
        price row exists first if there's no default level configured."""
        price = self.prices.filter(price_level__is_default=True).first() or self.prices.order_by('id').first()
        return price.price if price else Decimal('0')

    def price_for(self, level_name):
        price = self.prices.filter(price_level__name=level_name).first()
        return price.price if price else None


class ProductVariant(models.Model):
    """Reserved for future per-product options (size/flavor/color etc.).
    Not yet wired into batches, stock, or sale/purchase lines — every
    Product is still tracked as a single stocked unit for now."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    name = models.CharField(max_length=150)
    sku = models.CharField(max_length=64, unique=True, blank=True, null=True)
    barcode = models.CharField(max_length=64, unique=True, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.product} - {self.name}"


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/gallery/')
    caption = models.CharField(max_length=150, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_primary', 'id']

    def __str__(self):
        return f"{self.product} image"


class ProductBarcode(models.Model):
    """Extra scannable codes for a product beyond its primary Product.barcode
    (e.g. a manufacturer barcode alongside an internal one)."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='barcodes')
    barcode = models.CharField(max_length=64, unique=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ['-is_primary', 'id']

    def __str__(self):
        return self.barcode


class ProductPrice(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='prices')
    price_level = models.ForeignKey('masters.PriceLevel', on_delete=models.PROTECT, related_name='product_prices')
    price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        unique_together = ('product', 'price_level')
        ordering = ['price_level__name']

    def __str__(self):
        return f"{self.product} - {self.price_level}: {self.price}"
