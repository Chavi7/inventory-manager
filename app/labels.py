"""
Dragon Technologies Inventory Manager - asset label PDF generation.

Produces a printable PDF sheet of asset labels. Each label shows a QR code
encoding the asset's item_code (e.g. DT-LAP-001), the code in mono text, and
the item name. Laid out as a grid on Letter paper with light cut guides, so
labels can be printed on plain paper and cut out.

QR generation uses the `qrcode` library; the PDF is built with reportlab —
the same toolchain CLOCKIN uses for its badges.
"""
import io

import qrcode
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# --- Grid layout (Letter, portrait) --------------------------------------
PAGE_W, PAGE_H = letter           # 612 x 792 points (8.5" x 11")
MARGIN = 0.5 * inch
COLS = 3
ROWS = 5                          # 15 labels per page
GUTTER = 0.15 * inch

# Computed cell size.
CELL_W = (PAGE_W - 2 * MARGIN - (COLS - 1) * GUTTER) / COLS
CELL_H = (PAGE_H - 2 * MARGIN - (ROWS - 1) * GUTTER) / ROWS


def _make_qr_image(data):
    """Return an ImageReader of a QR code PNG for the given data string."""
    qr = qrcode.QRCode(
        version=None,                       # auto-size to fit the data
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def _truncate(text, limit):
    """Trim long item names so they fit on the label."""
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def _draw_label(c, x, y, item_code, item_name):
    """Draw one label inside the cell whose bottom-left corner is (x, y)."""
    # Light cut guide around the cell.
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.setLineWidth(0.5)
    c.rect(x, y, CELL_W, CELL_H, stroke=1, fill=0)

    # QR code, centered horizontally in the upper part of the cell.
    qr_size = min(CELL_W, CELL_H) * 0.58
    qr_x = x + (CELL_W - qr_size) / 2
    qr_y = y + CELL_H - qr_size - 0.12 * inch
    c.drawImage(_make_qr_image(item_code), qr_x, qr_y,
                width=qr_size, height=qr_size, preserveAspectRatio=True)

    # Asset code in mono, bold, centered below the QR.
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Courier-Bold", 11)
    code_y = qr_y - 0.16 * inch
    c.drawCentredString(x + CELL_W / 2, code_y, item_code)

    # Item name, smaller, centered below the code.
    c.setFont("Helvetica", 8)
    name_y = code_y - 0.16 * inch
    # Rough char budget based on cell width at 8pt Helvetica.
    c.drawCentredString(x + CELL_W / 2, name_y, _truncate(item_name, 26))


def build_label_pdf(items):
    """
    items: iterable of (item_code, item_name) tuples.
    Returns the PDF as bytes. Labels flow left-to-right, top-to-bottom,
    spilling onto additional pages as needed.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)

    per_page = COLS * ROWS
    for index, (item_code, item_name) in enumerate(items):
        slot = index % per_page
        if index > 0 and slot == 0:
            c.showPage()                    # start a new page

        col = slot % COLS
        row = slot // COLS
        x = MARGIN + col * (CELL_W + GUTTER)
        # Rows fill from the top of the page downward.
        y = PAGE_H - MARGIN - (row + 1) * CELL_H - row * GUTTER
        _draw_label(c, x, y, item_code, item_name)

    c.showPage()
    c.save()
    return buf.getvalue()
