"""Format-independent document blocks and their Markdown rendering."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

# Deepest Markdown heading produced: "#" title, "##" and "###" sections.
MAX_MARKDOWN_LEVEL = 3


@dataclass
class Block:
    text: str
    level: int | None = None  # heading rank, lower = more prominent; None = body text
    page: int | None = None  # PDF page the block starts on


def compress(ranks: Iterable[int]) -> dict[int, int]:
    """Map the ranks actually used to contiguous levels 1, 2, 3..."""
    return {rank: level for level, rank in enumerate(sorted(set(ranks)), start=1)}


def pick_title(blocks: list[Block], *, first_page_only: bool) -> str | None:
    """Remove and return the document title, if one heading clearly is.

    The title is the only heading at the top rank. In a PDF it must be on the first
    page (a notice may precede it); elsewhere nothing but headings may precede it.
    """
    headings = [i for i, b in enumerate(blocks) if b.level is not None]
    if not headings:
        return None
    top = min(blocks[i].level for i in headings)
    tops = [i for i in headings if blocks[i].level == top]
    if len(tops) != 1:
        return None
    index = tops[0]
    if first_page_only:
        if blocks[index].page != 1:
            return None
    elif any(b.level is None for b in blocks[:index]):
        return None
    return blocks.pop(index).text


def render_markdown(blocks: list[Block], title: str) -> str:
    """``# title``, then headings as ``##`` / ``###`` (deeper levels clamped) and body text."""
    levels = compress(b.level for b in blocks if b.level is not None)
    parts = [f"# {title}"]
    for block in blocks:
        if not block.text:
            continue
        if block.level is None:
            # Body lines starting with "#" (code comments, hashtags) must not read as headings.
            parts.append(re.sub(r"(?m)^(\s*)#", r"\1\\#", block.text))
        else:
            parts.append(f"{'#' * min(levels[block.level] + 1, MAX_MARKDOWN_LEVEL)} {block.text}")
    return "\n\n".join(parts)
