"""PDF pages to text lines, rebuilt from geometry.

pypdf reports each piece of text it draws with its text and page matrices. Lines are
formed from those real page positions -- not from pypdf's own line breaks, which are
wrong on some PDFs (e.g. flipped coordinate systems) -- and spaces are added where the
gap between two pieces is wider than a space.
"""

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace

from pypdf import PageObject, mult

from doc_loader.text import normalize

# Pieces whose baselines differ by less than this share of the font size share a line.
SAME_LINE_TOLERANCE = 0.5
# A horizontal gap wider than this share of the font size is a word space.
WORD_GAP = 0.2
# Average glyph width, in font sizes, for fonts that give no widths.
DEFAULT_GLYPH_WIDTH = 0.5
# Text whose baseline slope exceeds this is rotated (margin stamps, watermarks).
ROTATION_TOLERANCE = 0.1
# Share of a line's characters that must be bold / italic for the line to count as such.
STYLE_RATIO = 0.6
# Running headers / footers: the same text in the top or bottom share of the page...
RUNNING_MARGIN = 0.1
# ...on at least half of the pages (and 3 of them).
RUNNING_MIN_PAGES = 3
# A line's height above and below its baseline, in font sizes (typical ascent / descent).
ASCENT = 0.8
DESCENT = 0.2
# Reading order: an empty vertical band at least this wide (in font sizes) separates columns.
COLUMN_GAP = 1.0
# If more than this share of a page's lines sit outside the visible page, the engine's
# positions are wrong for that page (seen with pypdf on some Canva exports): its lines
# keep drawing order and are not used for margin detection.
MAX_OUTSIDE_RATIO = 0.2


@dataclass
class Piece:
    """A piece of text as drawn on the page; engines produce these, lines are built from them."""

    text: str
    x: float
    y: float  # baseline, page space (points, y up)
    size: float  # rendered font size
    width: float
    bold: bool
    italic: bool
    upright: bool


@dataclass
class Line:
    text: str
    page: int
    size: float
    bold: bool
    italic: bool
    upright: bool
    y: float  # baseline, points from the bottom of the page
    y_ratio: float  # 0 = bottom of the page, 1 = top
    x0: float = 0.0  # left edge
    x1: float = 0.0  # right edge
    positioned: bool = True  # False when the page's positions are unreliable

    def same_style(self, other: "Line", tolerance: float) -> bool:
        return self.bold == other.bold and abs(self.size - other.size) <= tolerance * max(self.size, other.size)

    @property
    def top(self) -> float:
        return self.y + ASCENT * self.size

    @property
    def bottom(self) -> float:
        return self.y - DESCENT * self.size


def page_lines(page: PageObject, page_no: int) -> list[Line]:
    """The page's lines, read with pypdf, in reading order.

    Positions are measured in the crop box -- the visible page -- which can be smaller
    than the media box (print margins), so margins and heights match what readers see.
    """
    box = page.cropbox
    left, bottom = float(box.left), float(box.bottom)
    pieces = [replace(piece, x=piece.x - left, y=piece.y - bottom) for piece in _pieces(page)]
    return lines_from_pieces(pieces, page_no, float(box.height) or 1.0, float(box.width) or 1.0)


def lines_from_pieces(pieces: list[Piece], page_no: int, page_height: float, page_width: float) -> list[Line]:
    """Build lines from positioned pieces -- the same way whatever engine read them --
    and put them in reading order, unless the positions are unreliable."""
    lines = [line for line in (_make_line(group, page_no, page_height) for group in _group(pieces)) if line.text]
    outside = sum(1 for line in lines if not _on_page(line, page_width, page_height))
    if lines and outside > MAX_OUTSIDE_RATIO * len(lines):
        return [replace(line, positioned=False) for line in lines]  # drawing order
    return reading_order(lines)


def _on_page(line: Line, page_width: float, page_height: float) -> bool:
    margin = line.size  # allow a line to touch the edge
    return -margin <= line.y <= page_height + margin and -margin <= line.x0 <= page_width + margin


def reading_order(lines: list[Line]) -> list[Line]:
    """A page's lines in reading order, by recursive XY-cut.

    PDFs draw text in any order (a title added last, text boxes, columns), so drawing
    order is not reading order. The page is cut at its widest empty band -- horizontal
    (between rows: top part first) or vertical (between columns: left part first) -- and
    each part is cut again until single lines remain. A full-width title is cut off above
    the columns, and each column is read top to bottom. Rotated lines keep drawing order,
    after the rest.
    """
    upright = [line for line in lines if line.upright]
    if not upright:
        return lines
    sizes = sorted(line.size for line in upright)
    min_column_gap = COLUMN_GAP * sizes[len(sizes) // 2]
    return _xy_cut(upright, min_column_gap) + [line for line in lines if not line.upright]


def _xy_cut(lines: list[Line], min_column_gap: float) -> list[Line]:
    if len(lines) <= 1:
        return lines
    row_gap, row_cut = _widest_gap([(line.bottom, line.top) for line in lines], 0.0)
    column_gap, column_cut = _widest_gap([(line.x0, line.x1) for line in lines], min_column_gap)
    if row_cut is None and column_cut is None:
        return sorted(lines, key=lambda line: (-line.y, line.x0))
    if column_cut is not None and (row_cut is None or column_gap > row_gap):
        in_first = [line.x1 <= column_cut for line in lines]  # left of the cut
    else:
        in_first = [line.bottom >= row_cut for line in lines]  # above the cut
    first = [line for line, keep in zip(lines, in_first) if keep]
    rest = [line for line, keep in zip(lines, in_first) if not keep]
    return _xy_cut(first, min_column_gap) + _xy_cut(rest, min_column_gap)


def _widest_gap(intervals: list[tuple[float, float]], min_gap: float) -> tuple[float, float | None]:
    """The widest empty space between intervals ``(start, end)``, and a position inside it."""
    best_gap, best_cut = 0.0, None
    ordered = sorted(intervals)
    reach = ordered[0][1]
    for start, end in ordered[1:]:
        gap = start - reach
        if gap > min_gap and gap > best_gap:
            best_gap, best_cut = gap, reach + gap / 2
        reach = max(reach, end)
    return best_gap, best_cut


def drop_running_lines(lines: list[Line], page_count: int) -> list[Line]:
    """Drop running headers and footers: the same text in the page margins of most pages."""
    if page_count < RUNNING_MIN_PAGES:
        return lines

    def key(line: Line) -> str | None:
        if not line.positioned:
            return None
        in_margin = line.y_ratio > 1 - RUNNING_MARGIN or line.y_ratio < RUNNING_MARGIN
        return re.sub(r"\d+", "#", line.text.lower()) if in_margin else None  # "Page 3" ~ "Page 4"

    pages_by_key: defaultdict[str, set[int]] = defaultdict(set)
    for line in lines:
        if (k := key(line)) is not None:
            pages_by_key[k].add(line.page)
    limit = max(RUNNING_MIN_PAGES, page_count // 2)
    return [line for line in lines if (k := key(line)) is None or len(pages_by_key[k]) < limit]


def _pieces(page: PageObject) -> list[Piece]:
    pieces: list[Piece] = []

    def visit(text: str, cm: list[float], tm: list[float], font: dict | None, font_size: float) -> None:
        text = text.replace("\n", "")  # pypdf's line breaks are ignored; positions decide
        if not text:
            return
        m = mult(tm, cm)  # text space -> page space
        size = font_size * math.hypot(m[2], m[3])
        if size <= 0:
            return
        bold, italic = font_style(str(font.get("/BaseFont", "")) if font else "")
        pieces.append(Piece(
            text=text,
            x=m[4],
            y=m[5],
            size=size,
            width=_text_width(text, font, font_size) * math.hypot(m[0], m[1]),
            bold=bold,
            italic=italic,
            upright=abs(m[1]) <= ROTATION_TOLERANCE * abs(m[0]),  # baseline direction (a, b)
        ))

    page.extract_text(visitor_text=visit)
    return pieces


def _text_width(text: str, font: dict | None, font_size: float) -> float:
    """Advance width in text space, from the font's /Widths when it has them."""
    try:
        widths = font.get("/Widths").get_object() if font else None
        first = int(font.get("/FirstChar", 0)) if font else 0
    except (AttributeError, TypeError, ValueError):
        widths = None
    if not widths:
        return len(text) * DEFAULT_GLYPH_WIDTH * font_size
    average = sum(float(w) for w in widths) / len(widths)
    total = sum(
        float(widths[ord(c) - first]) if 0 <= ord(c) - first < len(widths) else average for c in text
    )
    return total * font_size / 1000


def _group(pieces: list[Piece]) -> list[list[Piece]]:
    """A new line starts when the baseline moves by more than the tolerance."""
    groups: list[list[Piece]] = []
    for piece in pieces:
        if groups:
            anchor = next((p for p in reversed(groups[-1]) if p.text.strip()), groups[-1][-1])
            if abs(piece.y - anchor.y) <= SAME_LINE_TOLERANCE * max(anchor.size, piece.size):
                groups[-1].append(piece)
                continue
        groups.append([piece])
    return groups


def _make_line(pieces: list[Piece], page_no: int, page_height: float) -> Line:
    text = ""
    previous: Piece | None = None
    for piece in sorted(pieces, key=lambda p: p.x):
        if previous is not None and text and not text.endswith(" ") and not piece.text.startswith(" "):
            if piece.x - (previous.x + previous.width) > WORD_GAP * max(previous.size, piece.size):
                text += " "
        text += piece.text
        previous = piece
    inked = [p for p in pieces if p.text.strip()] or pieces
    return styled_line(
        text,
        [(p.text, p.size, p.bold, p.italic) for p in pieces],
        page_no=page_no,
        upright=all(p.upright for p in inked),
        y=inked[0].y,
        page_height=page_height,
        x0=min(p.x for p in inked),
        x1=max(p.x + p.width for p in inked),
    )


def styled_line(
    text: str,
    styles: list[tuple[str, float, bool, bool]],
    *,
    page_no: int,
    upright: bool,
    y: float,
    page_height: float,
    x0: float = 0.0,
    x1: float = 0.0,
) -> Line:
    """A line whose size, bold and italic come from a character vote over its parts
    ``(text, size, bold, italic)``: a line may mix a regular "1.1 " and a bold title."""
    sizes: Counter[float] = Counter()
    chars = bold = italic = 0
    for part, size, is_bold, is_italic in styles:
        n = len(part.strip())
        sizes[round(size, 1)] += n
        chars += n
        bold += n if is_bold else 0
        italic += n if is_italic else 0
    return Line(
        text=normalize(text),
        page=page_no,
        size=sizes.most_common(1)[0][0] if chars else 0.0,
        bold=chars > 0 and bold >= STYLE_RATIO * chars,
        italic=chars > 0 and italic >= STYLE_RATIO * chars,
        upright=upright,
        y=y,
        y_ratio=y / page_height,
        x0=x0,
        x1=x1,
    )


# Font names, after Docling's font_style.py (MIT, Copyright The Docling Contributors):
# whole style words only, and short abbreviations only as a full separator-delimited
# part ("Arial-Bd" is bold, "LinLibertineTB" is not).
_SUBSET_PREFIX = re.compile(r"^/?(?:[A-Z]{6}\+)?")
_FONT_TOKENS = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+")
_BOLD_WORDS = {"bold", "semibold", "demibold", "extrabold", "ultrabold", "black", "heavy"}
_ITALIC_WORDS = {"italic", "ital", "oblique", "slanted"}
_ABBREVIATIONS = {"bd": (True, False), "it": (False, True), "bdit": (True, True), "bi": (True, True)}


def font_style(name: str) -> tuple[bool, bool]:
    """``(bold, italic)`` from a PDF font name such as ``ABCDEF+Arial-BoldMT``."""
    bold = italic = False
    for part in re.split(r"[-_,+ ]+", _SUBSET_PREFIX.sub("", name)):
        if abbreviation := _ABBREVIATIONS.get(part.lower()):
            bold, italic = bold or abbreviation[0], italic or abbreviation[1]
            continue
        tokens = [t.lower() for t in _FONT_TOKENS.findall(part)]
        words = set(tokens) | {a + b for a, b in zip(tokens, tokens[1:])}  # "Semi" + "Bold"
        bold = bold or bool(words & _BOLD_WORDS)
        italic = italic or bool(words & _ITALIC_WORDS)
    return bold, italic
