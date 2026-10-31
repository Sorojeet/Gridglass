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
MAX_CELL_CHARS = 60
MAX_PDF_COLUMNS = 40


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return ""
        return f"{int(v):,}" if v.is_integer() and abs(v) < 1e15 else f"{v:,.2f}".rstrip("0").rstrip(".")
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, int):
        return f"{v:,}"
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


def _table(df: pl.DataFrame, usable: float) -> LongTable:
    font_size = 9 if df.width <= 6 else 8 if df.width <= 10 else 7 if df.width <= 16 else 6
    header_style = ParagraphStyle("h", fontName=BOLD, fontSize=font_size, textColor=colors.white,
                                  leading=font_size * 1.25, shaping=int(CAN_SHAPE))
    cell_style = ParagraphStyle("c", fontName=REGULAR, fontSize=font_size, leading=font_size * 1.3,
                                shaping=int(CAN_SHAPE))
    data = [[Paragraph(_escape(c), header_style) for c in df.columns]]
    data += [[_fmt(v) for v in row] for row in df.iter_rows()]
    texts = [row[:] for row in data[1:]]  # plain text, for measuring column widths
    if CAN_SHAPE:
        for row in data[1:]:
            for i, cell in enumerate(row):
                if COMPLEX.search(cell):
                    row[i] = Paragraph(_escape(cell), cell_style)

    # Column widths: share the page by typical content length, within sensible bounds.
    weights = []
    for i, name in enumerate(df.columns):
        sample = [len(r[i]) for r in texts[:200]] or [0]
        weights.append(min(max(len(name), sum(sample) / len(sample), 4), 30))
    total = sum(weights)
    widths = [usable * w / total for w in weights]

    numeric = [i for i, t in enumerate(df.dtypes) if t.is_numeric()]
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("FONTNAME", (0, 1), (-1, -1), REGULAR),
        ("FONTSIZE", (0, 1), (-1, -1), font_size),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ZEBRA]),
    ] + [("ALIGN", (i, 1), (i, -1), "RIGHT") for i in numeric]
    table = LongTable(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(style))
    return table


def _escape(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
