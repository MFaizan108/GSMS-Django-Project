from io import BytesIO

from django.template.loader import render_to_string
from xhtml2pdf import pisa


def render_to_pdf(template_name, context):
    """Render a template to PDF bytes via xhtml2pdf, or None if it failed.
    xhtml2pdf's CSS support is limited (no flexbox/grid, no external
    stylesheets) — PDF templates use plain inline-styled tables, deliberately
    separate from the Bootstrap-based web templates."""
    html = render_to_string(template_name, context)
    buffer = BytesIO()
    result = pisa.CreatePDF(html, dest=buffer)
    if result.err:
        return None
    return buffer.getvalue()
