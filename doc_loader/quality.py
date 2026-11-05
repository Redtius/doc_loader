"""Quality checks on a converted document, so bad extractions are not indexed silently.

Each check flags a known way text extraction fails. ``rejected`` documents must not be
indexed; ``warning`` documents can be, but need a human look.
"""

import re
from dataclasses import dataclass, field

# Lost spaces ("Let’scontinueourjourney") show as abnormally long "words": letters in
# words longer than LONG_WORD must stay under this share of all letters.
LONG_WORD = 25
MAX_LONG_WORD_RATIO = 0.2
MIN_LETTERS = 100
# Share of characters that are undecoded glyphs (glyph names, U+FFFD, private-use area).
MAX_ARTEFACT_RATIO = 0.001
# Pages without text: any is worth a warning, this share or more means a scanned document.
MAX_EMPTY_PAGE_RATIO = 0.5
# Short lines starting with a figure ("30 Dhs/trimestre") in this share of body lines,
# and at least this many, suggest a table read column by column (values apart from labels).
MAX_VALUE_LINE_RATIO = 0.15
MIN_VALUE_LINES = 10
VALUE_LINE_MAX_CHARS = 40
# Documents at least this long are expected to have headings.
MIN_PAGES_FOR_HEADINGS = 3

_WORD = re.compile(r"[^\W\d_]+")
_ARTEFACT = re.compile(
    r"�|[-]|/(?:uni[0-9A-F]{4}|g\d+|glyph\d+|[a-z]+\.(?:case|sc|alt|ss\d\d|lf|osf|tf))\b"
)


@dataclass
class Quality:
    status: str = "ok"  # ok | warning | rejected
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def _flag(self, status: str, reason: str) -> None:
        self.reasons.append(reason)
        if status == "rejected" or self.status == "ok":
            self.status = status


def assess(markdown: str, *, page_count: int | None = None, empty_pages: int = 0) -> Quality:
    quality = Quality()
    lines = markdown.splitlines()
    heading_lines = [l for l in lines if re.match(r"#{1,6} ", l)]
    body = [l for l in lines if l.strip() and l not in heading_lines]
    headings = max(len(heading_lines) - 1, 0)  # minus the title

    words = _WORD.findall("\n".join(body))
    letters = sum(len(w) for w in words)
    if letters >= MIN_LETTERS:
        long_letters = sum(len(w) for w in words if len(w) > LONG_WORD)
        quality.metrics["long_word_ratio"] = round(long_letters / letters, 2)
        if quality.metrics["long_word_ratio"] > MAX_LONG_WORD_RATIO:
            quality._flag("rejected", "words run together: spaces were lost in extraction")

    chars = sum(len(l) for l in body) or 1
    quality.metrics["artefact_ratio"] = round(len(_ARTEFACT.findall("\n".join(body))) / chars, 4)
    if quality.metrics["artefact_ratio"] > MAX_ARTEFACT_RATIO:
        quality._flag("rejected", "undecoded characters (glyph names or replacement characters)")

    if page_count:
        quality.metrics["empty_page_ratio"] = round(empty_pages / page_count, 2)
        if quality.metrics["empty_page_ratio"] >= MAX_EMPTY_PAGE_RATIO:
            quality._flag("rejected", f"{empty_pages}/{page_count} pages without text (scanned?)")
        elif empty_pages:
            quality._flag("warning", f"{empty_pages} page(s) without text skipped")
        if headings == 0 and page_count >= MIN_PAGES_FOR_HEADINGS:
            quality._flag("warning", "no headings found")

    value_lines = sum(1 for l in body if len(l) <= VALUE_LINE_MAX_CHARS and l.lstrip()[:1].isdigit())
    quality.metrics["value_line_ratio"] = round(value_lines / (len(body) or 1), 2)
    if value_lines >= MIN_VALUE_LINES and quality.metrics["value_line_ratio"] > MAX_VALUE_LINE_RATIO:
        quality._flag("warning", "many detached values: a table may have been read column by column")

    quality.metrics["headings"] = headings
    return quality
