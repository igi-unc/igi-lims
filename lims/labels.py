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
