"""Word (.docx) documents to blocks, with python-docx.

Headings come from styles only, as in Docling's Word backend: the built-in ``Title``
style is the document title; an outline level (``w:outlineLvl``, on the paragraph or
its style chain) is authoritative and language-independent; otherwise the built-in
"Heading N" styles. Paragraphs only made bold or larger by hand stay body text.
"""

from collections.abc import Iterator
from typing import BinaryIO

from docx import Document as open_docx
from docx.oxml.ns import qn
from docx.styles.style import BaseStyle
from docx.table import Table
from docx.text.paragraph import Paragraph

from doc_loader.blocks import Block
from doc_loader.text import normalize

# Built-in style names as python-docx reports them, whatever Word's display language
# ("Titre 1" in a French Word is "Heading 1"). Custom styles rely on their outline level.
_BUILTIN_TITLE = "Title"
_BUILTIN_HEADINGS = {f"Heading {level}": level for level in range(1, 10)}
_TITLE_RANK = 0  # above every heading level


def docx_blocks(stream: BinaryIO) -> list[Block]:
    doc = open_docx(stream)
    return [
        Block(_table_to_markdown(item))
        if isinstance(item, Table)
        else Block(normalize(item.text), _heading_rank(item))
        for item in doc.iter_inner_content()  # paragraphs and tables, in document order
    ]


def _heading_rank(paragraph: Paragraph) -> int | None:
    if not paragraph.text.strip():
        return None
    chain = list(_style_chain(paragraph.style))
    builtin = [s.name for s in chain if s.builtin]
    if _BUILTIN_TITLE in builtin:
        return _TITLE_RANK
    for p_pr in [paragraph._p.pPr, *(s.element.pPr for s in chain)]:
        if (level := _outline_level(p_pr)) is not None:
            return level
    return next((_BUILTIN_HEADINGS[name] for name in builtin if name in _BUILTIN_HEADINGS), None)


def _style_chain(style: BaseStyle | None) -> Iterator[BaseStyle]:
    while style is not None:
        yield style
        style = style.base_style


def _outline_level(p_pr: object | None) -> int | None:
    """Heading level 1-9 from ``w:outlineLvl`` 0-8; 9 means body text."""
    element = p_pr.find(qn("w:outlineLvl")) if p_pr is not None else None
    value = element.get(qn("w:val")) if element is not None else None
    return int(value) + 1 if value is not None and value.isdigit() and int(value) < 9 else None


def _table_to_markdown(table: Table) -> str:
    rows = [[normalize(cell.text).replace("|", "\\|") for cell in row.cells] for row in table.rows]
    if not rows:
        return ""
    header, *body = rows
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)
