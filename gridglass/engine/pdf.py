"""PDF export: a clean, readable table. Landscape for wide sheets, header row repeated on every page.

Text uses the bundled "Gridglass Sans" (Noto Sans Latin + Latin Extended + Devanagari, SIL Open Font License),
so ₹, accented names and Hindi all print. Cells in complex scripts (Indic) are shaped with HarfBuzz so
conjuncts like क्ष and त्र join correctly; plain cells stay plain strings, which keeps big exports fast.
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path

import polars as pl
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, TableStyle

FONT_DIR = Path(__file__).parent / "fonts"
COMPLEX = re.compile(r"[\u0900-\u0DFF]")  # Devanagari … Sinhala: needs shaping


def _register_fonts() -> tuple[str, str, bool]:
    """Register the bundled fonts once. Falls back to Helvetica if the files are missing."""
    try:
        pdfmetrics.registerFont(TTFont("GridglassSans", str(FONT_DIR / "GridglassSans-400.ttf")))
        pdfmetrics.registerFont(TTFont("GridglassSans-Bold", str(FONT_DIR / "GridglassSans-700.ttf")))
    except Exception:  # pragma: no cover - only when font files are absent
        return "Helvetica", "Helvetica-Bold", False
    try:
        import uharfbuzz  # noqa: F401  (enables shaping)
        shaping = True
    except ImportError:  # pragma: no cover
        shaping = False
    return "GridglassSans", "GridglassSans-Bold", shaping


REGULAR, BOLD, CAN_SHAPE = _register_fonts()

ACCENT = colors.HexColor("#0F766E")
ZEBRA = colors.HexColor("#F3F6F8")
GRID = colors.HexColor("#D9E0E6")
MAX_CELL_CHARS = 500  # long text wraps; only extreme cells are shortened
MAX_PDF_COLUMNS = 40


def plain_number(v: float) -> str:
    """Numbers exactly as in the data and the preview: no thousands commas, no rounding (1250, 125000.5, -0.125)."""
    if math.isnan(v) or math.isinf(v):
        return ""
    if v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    text = repr(v)
    if "e" in text:  # very large or very small: write it out in full rather than as 1e-07
        text = f"{v:.15f}".rstrip("0").rstrip(".")
    return text


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return plain_number(v)
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, int):
        return str(v)
    text = v.isoformat(sep=" ") if isinstance(v, datetime) else str(v)
    return text if len(text) <= MAX_CELL_CHARS else text[: MAX_CELL_CHARS - 1] + "…"


def write_pdf(df: pl.DataFrame, dest: str | Path, *, title: str = "Gridglass export") -> Path:
    """One table, header repeated on every page."""
    return write_pdf_sections([(title, df)], dest, title=title, first_is_title=True)


def write_pdf_sections(sections: list[tuple[str, pl.DataFrame]], dest: str | Path, *, title: str = "Gridglass export",
                       first_is_title: bool = False) -> Path:
    """Several tables, each starting on a new page with its own heading (one value per page)."""
    width = max(df.width for _, df in sections)
    if width > MAX_PDF_COLUMNS:
        from .errors import ExportError

        raise ExportError(f"PDF export fits at most {MAX_PDF_COLUMNS} columns; this has {width}. "
                          "Remove some columns first, or export as XLSX.")
    page = landscape(A4) if width > 6 else A4
    margin = 12 * mm
    usable = page[0] - 2 * margin
    title_style = ParagraphStyle("t", fontName=BOLD, fontSize=13, leading=17, shaping=int(CAN_SHAPE))
    sub_style = ParagraphStyle("s", fontName=REGULAR, fontSize=8, textColor=colors.HexColor("#5B6573"),
                               shaping=int(CAN_SHAPE))

    story = []
    for n, (heading, df) in enumerate(sections):
        if n:
            story.append(PageBreak())
        sub = f"{df.height:,} rows · {df.width} columns" + ("" if first_is_title else f" · {title}")
        story += [Paragraph(_escape(heading), title_style), Paragraph(_escape(sub), sub_style),
                  Spacer(1, 4 * mm), _table(df, usable)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(REGULAR, 7)
        canvas.setFillColor(colors.HexColor("#5B6573"))
        canvas.drawString(margin, 7 * mm, "Made with Gridglass")
        canvas.drawRightString(page[0] - margin, 7 * mm, f"Page {doc.page}")
        canvas.restoreState()

    dest = Path(dest)
    doc = SimpleDocTemplate(str(dest), pagesize=page, leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=14 * mm, title=title, creator="Gridglass")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return dest


PAD = 4  # left/right padding inside each cell, in points


def _table(df: pl.DataFrame, usable: float) -> LongTable:
    """A table that fits the page: columns sized by their real text width, long text wrapped inside its column."""
    font_size = 9 if df.width <= 6 else 8 if df.width <= 10 else 7 if df.width <= 16 else 6
    shaping = int(CAN_SHAPE)
    header_style = ParagraphStyle("h", fontName=BOLD, fontSize=font_size, textColor=colors.white,
                                  leading=font_size * 1.3, shaping=shaping, splitLongWords=1)
    cell_style = ParagraphStyle("c", fontName=REGULAR, fontSize=font_size, leading=font_size * 1.35,
                                shaping=shaping, splitLongWords=1)
    complex_style = ParagraphStyle("cx", parent=cell_style, leading=font_size * 1.6)  # Indic marks need room
    numeric = [t.is_numeric() for t in df.dtypes]
    texts = [[_fmt(v) for v in row] for row in df.iter_rows()]
    widths = _column_widths(df.columns, texts, numeric, usable, font_size)

    data = [[Paragraph(_escape(c), header_style) for c in df.columns]]
    for row in texts:
        out = []
        for i, cell in enumerate(row):
            fits = pdfmetrics.stringWidth(cell, REGULAR, font_size) <= widths[i] - 2 * PAD
            if COMPLEX.search(cell) and CAN_SHAPE:
                out.append(Paragraph(_escape(cell), complex_style))
            elif fits or numeric[i]:
                out.append(cell)  # plain strings are fast; most cells fit on one line
            else:
                out.append(Paragraph(_escape(cell), cell_style))  # wraps inside its own column
        data.append(out)

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("FONTNAME", (0, 1), (-1, -1), REGULAR),
        ("FONTSIZE", (0, 1), (-1, -1), font_size),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), PAD),
        ("RIGHTPADDING", (0, 0), (-1, -1), PAD),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
    ] + [("ALIGN", (i, 1), (i, -1), "RIGHT") for i, n in enumerate(numeric) if n]
    table = LongTable(data, colWidths=widths, repeatRows=1, splitByRow=1)
    table.setStyle(TableStyle(style))
    return table


def _column_widths(names: list[str], texts: list[list[str]], numeric: list[bool], usable: float,
                   font_size: float) -> list[float]:
    """Share the page width between columns using the real width of their text.

    Every column gets at least its longest header word (headers never break mid-word if it can
    be helped) and numbers keep their full width. The rest goes to the columns with long text,
    which then wrap.
    """
    measure = lambda t, font=REGULAR: pdfmetrics.stringWidth(t, font, font_size) + 2 * PAD
    sample = texts[:500]
    natural, minimum = [], []
    for i, name in enumerate(names):
        cells = sorted(measure(r[i]) for r in sample) or [0.0]
        typical = cells[min(len(cells) - 1, int(len(cells) * 0.9))]  # 90th percentile: ignore a few very long cells
        header_word = max((measure(w, BOLD) for w in str(name).split()), default=0.0)
        numbers = cells[-1] if numeric[i] else 0.0  # numbers must never wrap
        minimum.append(max(header_word, numbers, 24.0))
        natural.append(max(typical, measure(str(name), BOLD), minimum[-1]))

    if sum(natural) <= usable:  # everything fits on one line: spread the spare room evenly
        spare = (usable - sum(natural)) / len(natural)
        return [w + spare for w in natural]
    if sum(minimum) >= usable:  # very many columns: fall back to proportional minimums
        return [usable * m / sum(minimum) for m in minimum]
    # Shrink only the part above each column's minimum, in proportion, so long text wraps.
    extra = [n - m for n, m in zip(natural, minimum)]
    room = usable - sum(minimum)
    return [m + room * e / sum(extra) for m, e in zip(minimum, extra)]


def _escape(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
