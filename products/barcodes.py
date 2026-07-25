import base64
import io

import barcode
from barcode.writer import ImageWriter


def generate_barcode_data_uri(code):
    """Render `code` as a Code128 barcode PNG and return it as a base64
    data: URI, ready to drop straight into an <img src=...>."""
    writer = ImageWriter()
    writer.dpi = 300
    barcode_obj = barcode.get('code128', code, writer=writer)
    buffer = io.BytesIO()
    barcode_obj.write(buffer, options={'write_text': False, 'quiet_zone': 2})
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f"data:image/png;base64,{encoded}"
