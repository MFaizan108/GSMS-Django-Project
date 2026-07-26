import socket
from contextlib import contextmanager

from django.core.mail import get_connection, EmailMessage


class EmailNotConfigured(Exception):
    pass


@contextmanager
def _force_ipv4():
    """Render's (and many container hosts') network has no IPv6 route, but
    DNS often still returns an IPv6 address alongside the IPv4 one, and
    Python's socket.create_connection() may try that first — producing
    `[Errno 101] Network is unreachable` even though the SMTP host is
    perfectly reachable over IPv4.

    This filters getaddrinfo() to IPv4-only for the duration of the SMTP
    connect+send below, rather than resolving the hostname to a literal IP
    up front — smtplib uses the *hostname string* we pass it as the TLS
    server_hostname for STARTTLS/SSL, so substituting a raw IP there would
    break certificate hostname verification against the mail server's real
    certificate. Restored immediately after, so it can't affect any other
    network call in the process."""
    original_getaddrinfo = socket.getaddrinfo

    def ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
        return original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = ipv4_only
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo


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
    with _force_ipv4():
        message.send()
