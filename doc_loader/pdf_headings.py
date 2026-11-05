"""PDF lines to heading and paragraph blocks.

Whether a line is a heading: it is in the PDF's bookmarks, or it is set larger than
the body text (or bold at body size), short, upright, and doesn't end like a sentence.
Lines of a printed table of contents are never headings.

Heading levels:
- with bookmarks, the levels they declare -- applied to bookmarked headings, and to
  other headings sharing a bookmarked heading's style;
- otherwise by style (font size, then bold), with numbering (I. > 1. > 1.1 > A.) to
  separate headings that share a style.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from doc_loader.blocks import Block, compress
from doc_loader.pdf_layout import Line

# A heading candidate is at least this much larger than the body text...
HEADING_SIZE_RATIO = 1.15
# ...or bold at body size and no longer than this.
MAX_BOLD_HEADING_CHARS = 80
# Longer text, or text ending with one of these, is a paragraph, not a heading.
MAX_HEADING_CHARS = 120
SENTENCE_ENDINGS = ".,;"
# Font sizes within 5 % are one size (the same font measures taller with descenders).
SIZE_TOLERANCE = 0.05
# Heading lines of one style this close (in font sizes) are one wrapped heading:
# wrapped lines sit ~1.2 font sizes apart, separate blocks further.
WRAP_LINE_GAP = 1.5
# Bookmark title similarity needed to match a line (Docling's default).
BOOKMARK_MATCH = 0.8
# Bookmark matches needed before bookmarks are trusted to describe what headings look like.
MIN_BOOKMARK_MATCHES = 3
# A table-of-contents page: among the first pages, at least this many lines ending with
# a page number, making up half of its lines...
TOC_MIN_ENTRIES = 5
# ...with page numbers that mostly don't decrease (tariff amounts do).
TOC_ORDERED_RATIO = 0.8


@dataclass
class _Group:
    lines: list[Line]
    heading: bool
    depth: int | None = None  # bookmark depth, when matched
    rank: int = field(default=0)

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines)


def pdf_blocks(lines: list[Line], bookmarks: list[tuple[str, int, int]], page_count: int) -> list[Block]:
    if not lines:
        return []
    body_size = _body_size(lines)
    toc = _toc_lines(lines, page_count)
    matched = _match_bookmarks(lines, bookmarks)
    candidate = [
        i in matched or (i not in toc and _looks_like_heading(line, body_size))
        for i, line in enumerate(lines)
    ]
    if len(matched) >= MIN_BOOKMARK_MATCHES:
        # The document declares its outline: other headings must look like the declared
        # ones, or be a first-page title more prominent than all of them. Large text in
        # figures, bold table headers and author names otherwise pass for sections.
        declared = [lines[i] for i in matched]
        largest = max(d.size for d in declared)
        candidate = [
            is_candidate and (
                i in matched
                or any(line.same_style(d, SIZE_TOLERANCE) for d in declared)
                or (line.page == 1 and line.size > largest * (1 + SIZE_TOLERANCE))
            )
            for i, (line, is_candidate) in enumerate(zip(lines, candidate))
        ]

    groups = _group(lines, candidate, matched)
    headings = [g for g in groups if g.heading]
    _rank(headings)
    return [
        Block(g.text, g.rank, g.lines[0].page) if g.heading else Block("\n".join(l.text for l in g.lines), page=g.lines[0].page)
        for g in groups
    ]


def _body_size(lines: list[Line]) -> float:
    """The font size carrying the most characters."""
    chars: Counter[float] = Counter()
    for line in lines:
        if line.upright:
            chars[round(line.size * 2) / 2] += len(line.text)
    return chars.most_common(1)[0][0] if chars else 0.0


def _is_heading_text(text: str) -> bool:
    return 0 < len(text) <= MAX_HEADING_CHARS and text[-1] not in SENTENCE_ENDINGS


def _looks_like_heading(line: Line, body_size: float) -> bool:
    if not line.upright or not _is_heading_text(line.text) or not any(c.isalpha() for c in line.text):
        return False
    if line.size >= body_size * HEADING_SIZE_RATIO:
        return True
    return line.bold and line.size >= body_size * (1 - SIZE_TOLERANCE) and len(line.text) <= MAX_BOLD_HEADING_CHARS


def _group(lines: list[Line], candidate: list[bool], matched: dict[int, int]) -> list[_Group]:
    """Join wrapped headings, and consecutive body lines into paragraphs."""
    groups: list[_Group] = []
    for i, line in enumerate(lines):
        if groups:
            group = groups[-1]
            last = group.lines[-1]
            wrapped = (
                group.heading and candidate[i] and i not in matched
                and last.page == line.page and last.same_style(line, SIZE_TOLERANCE)
                and 0 < last.y - line.y <= WRAP_LINE_GAP * line.size
            )
            if wrapped or (not group.heading and not candidate[i]):
                group.lines.append(line)
                continue
        groups.append(_Group([line], candidate[i], matched.get(i)))
    # Lines that each looked like a heading may join into a paragraph set in a larger font.
    for group in groups:
        if group.heading and group.depth is None and not _is_heading_text(group.text):
            group.heading = False
    return groups


# --------------------------------------------------------------------------- levels


def _rank(headings: list[_Group]) -> None:
    """Set each heading's rank (lower = more prominent)."""
    if not headings:
        return
    clusters = _size_clusters({g.lines[0].size for g in headings})

    def style(g: _Group) -> tuple[int, bool]:
        return clusters[g.lines[0].size], not g.lines[0].bold

    bookmarked = [g for g in headings if g.depth is not None]
    if bookmarked:
        depth_by_style: dict[tuple[int, bool], int] = {}
        for g in bookmarked:
            depth_by_style[style(g)] = min(depth_by_style.get(style(g), g.depth), g.depth)
        top_style, deepest = min(depth_by_style), max(depth_by_style.values())
        # Styles no bookmark uses: above the outline if more prominent than its top
        # style (a cover title), below it otherwise; in style order either way.
        above = sorted({style(g) for g in headings if style(g) not in depth_by_style and style(g) < top_style})
        below = sorted({style(g) for g in headings if style(g) not in depth_by_style and style(g) > top_style})
        for g in headings:
            s = style(g)
            if g.depth is not None:
                g.rank = g.depth
            elif s in depth_by_style:
                g.rank = depth_by_style[s]
            elif s in above:
                g.rank = above.index(s) - len(above)
            else:
                g.rank = deepest + 1 + below.index(s)
        return

    # No bookmarks: style first, numbering to separate headings of one style. Unnumbered
    # headings take the top numbering rank of their style.
    numbering = [_numbering_rank(g.text) for g in headings]
    top_numbering: defaultdict[tuple[int, bool], int] = defaultdict(int)
    for g, n in zip(headings, numbering):
        if n is not None:
            s = style(g)
            top_numbering[s] = min(top_numbering.get(s, n), n)
    keys = [(*style(g), n if n is not None else top_numbering[style(g)]) for g, n in zip(headings, numbering)]
    ranks = compress(keys)
    for g, key in zip(headings, keys):
        g.rank = ranks[key]


def _size_clusters(sizes: set[float]) -> dict[float, int]:
    """Sizes within ``SIZE_TOLERANCE`` of the next larger one share a cluster; largest = 0."""
    clusters: dict[float, int] = {}
    index, previous = 0, None
    for size in sorted(sizes, reverse=True):
        if previous is not None and previous - size > SIZE_TOLERANCE * previous:
            index += 1
        clusters[size] = index
        previous = size
    return clusters


# Leading numbering, most prominent first (after Docling's heading hierarchy).
_KEYWORD_NUMBERING = [
    re.compile(r"^(part|partie|book|livre)\s+([0-9]+|[ivxlc]+)\b", re.IGNORECASE),
    re.compile(r"^(chapter|chapitre)\s+([0-9]+|[ivxlc]+)\b", re.IGNORECASE),
    re.compile(r"^(article|section|annex|annexe|appendix)\s+([0-9]+|[ivxlc]+|[a-z])\b|^§\s*\d", re.IGNORECASE),
]
_ROMAN = re.compile(r"^[IVXLC]+[.)]\s")
_DECIMAL = re.compile(r"^(\d+(?:\.\d+)*)(?:[.)]\s|\s)")  # "1. ", "1) ", "1.2 ", "1.2.3 "
_SINGLE_NUMBER = re.compile(r"^\d+\s")  # "2024 Rapport": not numbering on its own
_UPPER_LETTER = re.compile(r"^[A-Z][.)]\s")
_LOWER_LETTER = re.compile(r"^\(?[a-z][.)]\s")


def _numbering_rank(text: str) -> int | None:
    for rank, pattern in enumerate(_KEYWORD_NUMBERING):
        if pattern.match(text):
            return rank
    if _ROMAN.match(text):
        return 3
    if (m := _DECIMAL.match(text)) and not (_SINGLE_NUMBER.match(text) and "." not in m.group(0)):
        return 4 + m.group(1).count(".")
    if _UPPER_LETTER.match(text):
        return 8
    if _LOWER_LETTER.match(text):
        return 9
    return None


# --------------------------------------------------------------------------- outline

_LEADING_NUMBER = re.compile(r"^\s*(?:\d+(?:\.\d+)*|[IVXLC]+|[A-Za-z])[.)]?\s+")


def _match_bookmarks(lines: list[Line], bookmarks: list[tuple[str, int, int]]) -> dict[int, int]:
    """Line index -> bookmark depth, for lines confidently matched on the bookmark's page."""
    by_page: defaultdict[int, list[int]] = defaultdict(list)
    for i, line in enumerate(lines):
        if _is_heading_text(line.text):
            by_page[line.page].append(i)
    matched: dict[int, int] = {}
    for title, page, depth in bookmarks:
        scored = [(_similarity(lines[i].text, title), i) for i in by_page[page] if i not in matched]
        score, best = max(scored, default=(0.0, None))
        if best is not None and score >= BOOKMARK_MATCH:
            matched[best] = depth
    return matched


def _similarity(line_text: str, title: str) -> float:
    """0..1, ignoring leading numbering; one containing the other counts as 0.92 (Docling)."""
    a, b = (_LEADING_NUMBER.sub("", t).lower().strip() for t in (line_text, title))
    if not a or not b:
        return 0.0
    if len(a) >= 4 and len(b) >= 4 and (a in b or b in a):
        return max(0.92, SequenceMatcher(None, a, b).ratio())
    return SequenceMatcher(None, a, b).ratio()


# Text, then a page number, possibly after dot leaders or glued to the text ("Hijack9").
_TOC_ENTRY = re.compile(r"^(?=.*[^\W\d_]).*[^\d\s.…][\s.…]*(\d{1,4})$")


def _toc_lines(lines: list[Line], page_count: int) -> set[int]:
    """Lines of a printed table of contents (navigation, never headings)."""
    entries: defaultdict[int, list[tuple[int, int]]] = defaultdict(list)
    per_page: Counter[int] = Counter(line.page for line in lines)
    for i, line in enumerate(lines):
        if (m := _TOC_ENTRY.match(line.text)) and 1 <= int(m.group(1)) <= page_count:
            entries[line.page].append((i, int(m.group(1))))
    result: set[int] = set()
    for page, page_entries in entries.items():
        numbers = [n for _, n in page_entries]
        ordered = sum(b >= a for a, b in zip(numbers, numbers[1:]))
        if (
            page <= max(5, page_count // 5)
            and len(page_entries) >= TOC_MIN_ENTRIES
            and len(page_entries) >= per_page[page] / 2
            and ordered >= TOC_ORDERED_RATIO * (len(numbers) - 1)
        ):
            result.update(i for i, _ in page_entries)
    return result
