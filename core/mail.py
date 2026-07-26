import base64
import socket
from contextlib import contextmanager

import requests
from django.core.mail import get_connection, EmailMessage


class EmailNotConfigured(Exception):
    pass


BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'


def _send_via_brevo(store, subject, body, to, attachments):
    """Brevo's HTTPS API — this is the reliable path on hosts like Render
    that block outbound raw SMTP traffic (port 443 always gets through,
    since blocking it would break the platform itself)."""
    payload = {
        'sender': {'name': store.store_name or 'Store', 'email': store.from_email},
        'to': [{'email': to}],
        'subject': subject,
        'textContent': body,
    }
    if attachments:
        payload['attachment'] = [
            {'name': filename, 'content': base64.b64encode(content).decode('ascii')}
            for filename, content, _mimetype in attachments
        ]
    resp = requests.post(
        BREVO_API_URL,
        json=payload,
        headers={'api-key': store.brevo_api_key, 'Accept': 'application/json', 'Content-Type': 'application/json'},
        timeout=15,
    )
    if resp.status_code >= 300:
        try:
            detail = resp.json().get('message', resp.text)
        except ValueError:
            detail = resp.text
        raise RuntimeError(f"Brevo rejected the email ({resp.status_code}): {detail}")


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


def _send_via_smtp(store, subject, body, to, attachments):
    """Fallback for local dev / networks that actually allow outgoing SMTP.
    Most PaaS hosts (Render included) block this outright — see
    _force_ipv4's docstring and _send_via_brevo above for why the API path
    is what's actually reliable in production."""
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


def send_store_email(subject, body, to, attachments=None):
    """Send an email using the settings stored in StoreSettings (set via the
    Settings page, not settings.py/.env) — read fresh on every call, so
    changing them in the UI takes effect immediately.

    Uses Brevo's HTTP API whenever an API key is configured (the reliable
    option on most hosting platforms); otherwise falls back to SMTP.

    `attachments`: optional list of (filename, content_bytes, mimetype)."""
    from settings_app.models import StoreSettings

    store = StoreSettings.get_solo()
    if not store.from_email:
        raise EmailNotConfigured("Email is not configured yet — set a From address in Settings.")

    if store.brevo_api_key:
        _send_via_brevo(store, subject, body, to, attachments)
        return

    if not store.smtp_host:
        raise EmailNotConfigured("Email is not configured yet — set a Brevo API key or SMTP host in Settings.")
    _send_via_smtp(store, subject, body, to, attachments)
