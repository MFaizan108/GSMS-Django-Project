from django.db import models


class StoreSettings(models.Model):
    store_name = models.CharField(max_length=150, default='My General Store')
    owner_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    logo = models.ImageField(upload_to='settings/', null=True, blank=True)
    invoice_footer = models.CharField(max_length=255, blank=True, default='Thank you for shopping with us!')
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default='PKR')

    # Outgoing email (invoice sending), read fresh at send-time by
    # core.mail.get_store_email_connection — never cached into
    # django.conf.settings, so changing these here takes effect immediately,
    # no server restart needed.
    smtp_host = models.CharField(max_length=255, blank=True)
    smtp_port = models.PositiveIntegerField(null=True, blank=True, default=587)
    smtp_username = models.CharField(max_length=255, blank=True)
    smtp_password = models.CharField(max_length=255, blank=True)
    smtp_use_tls = models.BooleanField(default=True)
    from_email = models.EmailField(blank=True)

    class Meta:
        verbose_name = 'Store Settings'
        verbose_name_plural = 'Store Settings'

    def __str__(self):
        return self.store_name

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
