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

    port = store.smtp_port or 587
    # Port 465 is implicit-SSL only (STARTTLS on it fails silently/hangs);
    # 587 (and everything else) expects STARTTLS. There's no separate
    # use_ssl field in Settings, so infer it from the port instead of
    # forcing the user to know which knob to flip.
    use_ssl = port == 465
    connection = get_connection(
        host=store.smtp_host,
        port=port,
        username=store.smtp_username or None,
        password=store.smtp_password or None,
        use_tls=store.smtp_use_tls and not use_ssl,
        use_ssl=use_ssl,
        # Without this, a bad host/port or a blocked outbound port hangs on the
        # OS-level TCP timeout (minutes) — long enough for gunicorn's own worker
        # timeout to kill the request first, turning a catchable SMTP error into
        # an opaque 500. Fail fast so the caller's try/except can handle it.
        timeout=10,
    )
    message = EmailMessage(subject=subject, body=body, from_email=store.from_email, to=[to], connection=connection)
    for filename, content, mimetype in (attachments or []):
        message.attach(filename, content, mimetype)
    message.send()
