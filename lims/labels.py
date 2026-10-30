"""Tube label preview: the label text rows beside a 2D (Data Matrix) barcode of the full sample ID.

This is a preview of what the printer should produce, drawn as SVG so it is crisp at any zoom.
Data Matrix is the usual 2D code on cryotube labels; any phone or lab scanner that reads QR
codes generally reads it too. The barcode encodes exactly the sample ID, nothing else.
"""
from xml.sax.saxutils import escape

from ppf.datamatrix import DataMatrix

from . import samples as svc


def barcode_matrix(text):
    """Rows of 0/1 modules for a Data Matrix symbol (finder pattern included, no quiet zone)."""
    return [[1 if v else 0 for v in row] for row in DataMatrix(text).matrix]


def _modules_path(matrix, x0, y0, size):
    """One SVG path of horizontal runs: far smaller than a rect per module."""
    parts = []
    for r, row in enumerate(matrix):
        c = 0
        while c < len(row):
            if row[c]:
                start = c
                while c < len(row) and row[c]:
                    c += 1
                parts.append(f"M{x0 + start * size:g} {y0 + r * size:g}h{(c - start) * size:g}v{size:g}h{-(c - start) * size:g}z")
            else:
                c += 1
    return "".join(parts)


def label_svg(sample):
    """SVG of the whole label: barcode on the left, text rows on the right."""
    rows = svc.label_rows(sample)
    matrix = barcode_matrix(sample["sample_id"])
    module = 3                                  # px per module in the preview
    quiet = 2 * module                          # quiet zone around the symbol
    code = len(matrix) * module
    font, line = 13, 17
    text_x = quiet * 2 + code + 8
    text_w = max(len(r) for r in rows) * font * 0.62
    width = int(text_x + text_w + 10)
    height = int(max(code + 2 * quiet, len(rows) * line + 12))
    code_y = (height - code) / 2
    text_y0 = (height - len(rows) * line) / 2 + font
    texts = "".join(f'<text x="{text_x:g}" y="{text_y0 + i * line:g}">{escape(r)}</text>' for i, r in enumerate(rows))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'role="img" aria-label="Label for {escape(sample["sample_id"])}">'
            f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="6" fill="#fff" stroke="#9aa3ad" stroke-dasharray="4 3"/>'
            f'<path fill="#000" d="{_modules_path(matrix, quiet * 1.5, code_y, module)}"/>'
            f'<g font-family="ui-monospace, Menlo, Consolas, monospace" font-size="{font}" fill="#000">{texts}</g></svg>')


# ------------------------------------------------------------------ print layout (exact label stock size)

_MONO = "DejaVu Sans Mono, Consolas, Menlo, Liberation Mono, monospace"


def _stock(width_in=None, height_in=None, dpi=None):
    from flask import current_app
    st = current_app.config["LABEL_STOCK"]
    dpi = int(dpi or st["dpi"])
    return round(float(width_in or st["width_in"]) * dpi), round(float(height_in or st["height_in"]) * dpi), dpi


def _fit_rows(rows, x, width, top, height, max_font):
    """SVG <text> rows filling a box. Characters are condensed (textLength) rather than shrunk when the box is
    narrow, which keeps them taller and easier to read on a 1/2-inch label."""
    n = max(len(rows), 1)
    longest = max((len(r) for r in rows), default=1) or 1
    font = min(max_font, height / (n * 1.12))
    natural = font * 0.6                       # monospace advance per character
    char_w = min(natural, width / longest)     # condense to fit the widest row
    line = height / n
    out = []
    for i, r in enumerate(rows):
        y = top + line * i + (line + font * 0.72) / 2
        out.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{font:.1f}" textLength="{len(r) * char_w:.1f}" '
                   f'lengthAdjust="spacingAndGlyphs">{escape(r)}</text>')
    return "".join(out)


def label_print_svg(sample, width_in=None, height_in=None, dpi=None):
    """The label as it goes to the printer: an SVG exactly the stock size in printer dots (default M6-17-492,
    1.0 x 0.5 in at 300 dpi = 300 x 150). Barcode modules are whole dots so the symbol prints crisply."""
    from . import samples as svc
    W, H, dpi = _stock(width_in, height_in, dpi)
    margin = max(2, round(0.035 * dpi))          # ~0.9 mm white edge: tolerates the printer's placement error
    matrix = barcode_matrix(sample["sample_id"])
    n = len(matrix)
    module = max(2, (H - 2 * margin) // (n + 2))          # +2: one-module quiet zone each side
    code = n * module
    cx, cy = margin + module, (H - code) // 2
    tx = margin + (n + 2) * module + round(0.015 * dpi)
    rows = svc.label_rows(sample)
    text = _fit_rows(rows, tx, W - tx - margin, margin, H - 2 * margin, max_font=0.11 * dpi)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'shape-rendering="crispEdges" data-dpi="{dpi}">'
            f'<rect width="{W}" height="{H}" fill="#fff"/>'
            f'<path fill="#000" d="{_modules_path(matrix, cx, cy, module)}"/>'
            f'<g font-family="{_MONO}" font-weight="700" fill="#000" text-rendering="geometricPrecision">{text}</g></svg>')


def header_print_svg(lines, width_in=None, height_in=None, dpi=None):
    """A job separator label: a few short text lines in a box (who asked, how many labels)."""
    W, H, dpi = _stock(width_in, height_in, dpi)
    margin = max(2, round(0.03 * dpi))
    text = _fit_rows(lines, margin * 2, W - 4 * margin, margin, H - 2 * margin, max_font=0.12 * dpi)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" data-dpi="{dpi}">'
            f'<rect width="{W}" height="{H}" fill="#fff"/>'
            f'<rect x="{margin / 2}" y="{margin / 2}" width="{W - margin}" height="{H - margin}" fill="none" stroke="#000" '
            f'stroke-width="{max(2, dpi // 100)}" stroke-dasharray="{dpi // 25} {dpi // 50}"/>'
            f'<g font-family="{_MONO}" font-weight="700" fill="#000">{text}</g></svg>')


def alignment_print_svg(width_in=None, height_in=None, dpi=None, caption=""):
    """Calibration label: a border one dot inside the edge, TOP / LEFT / RIGHT / BOTTOM marks and an arrow, so a
    photo of a test print shows exactly how the driver places and turns the page."""
    W, H, dpi = _stock(width_in, height_in, dpi)
    t = max(2, dpi // 100)
    f = round(0.075 * dpi)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" data-dpi="{dpi}">'
            f'<rect width="{W}" height="{H}" fill="#fff"/>'
            f'<rect x="{t / 2}" y="{t / 2}" width="{W - t}" height="{H - t}" fill="none" stroke="#000" stroke-width="{t}"/>'
            f'<g font-family="{_MONO}" font-weight="700" fill="#000" text-anchor="middle">'
            f'<text x="{W / 2}" y="{f + 2 * t}" font-size="{f}">TOP</text>'
            f'<text x="{W / 2}" y="{H - 3 * t}" font-size="{f}">BOTTOM</text>'
            f'<text x="{3 * t}" y="{H / 2 + f / 3}" font-size="{f}" text-anchor="start">LEFT</text>'
            f'<text x="{W - 3 * t}" y="{H / 2 + f / 3}" font-size="{f}" text-anchor="end">RIGHT</text>'
            f'<text x="{W / 2}" y="{H * 0.72}" font-size="{f * 0.8:.0f}">{escape(caption)}</text></g>'
            f'<path d="M{W / 2} {H * 0.36} l{-f / 2} {f * 0.6} h{f} z" fill="#000"/></svg>')
