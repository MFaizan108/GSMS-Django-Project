from django.core.mail import get_connection, EmailMessage


class EmailNotConfigured(Exception):
    pass


def send_store_email(subject, body, to, attachments=None):
    """Send an email using the SMTP settings stored in StoreSettings (set via
    the Settings page, not settings.py/.env) — read fresh on every call, so
    changing them in the UI takes effect immediately.

    `attachments`: optional list of (filename, content_bytes, mimetype)."""
    from settings_app.models import StoreSettings

    store = StoreSettings.get_solo()
    if not store.smtp_host or not store.from_email:
        raise EmailNotConfigured("Email is not configured yet — set SMTP host and From address in Settings.")

    connection = get_connection(
        host=store.smtp_host,
        port=store.smtp_port or 587,
        username=store.smtp_username or None,
        password=store.smtp_password or None,
        use_tls=store.smtp_use_tls,
    )
    message = EmailMessage(subject=subject, body=body, from_email=store.from_email, to=[to], connection=connection)
    for filename, content, mimetype in (attachments or []):
        message.attach(filename, content, mimetype)
    message.send()
