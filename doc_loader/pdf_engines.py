"""Reading a PDF's lines and bookmarks with either engine.

- ``pypdf`` (default, BSD licence): lines rebuilt from geometry in ``pdf_layout``.
- ``pymupdf`` (optional, AGPL-3.0 or commercial licence -- check before production
  use): MuPDF gives lines with their spans, fonts and positions directly, and reads
  word spaces that pypdf loses on some PDFs. Imported only when requested.

Both produce the same ``Line`` objects, so headings, quality and rendering are shared.
"""

import logging
from dataclasses import dataclass
from typing import BinaryIO, Literal

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from doc_loader.errors import LoaderError
from doc_loader.pdf_layout import ROTATION_TOLERANCE, Line, Piece, font_style, lines_from_pieces, page_lines

logger = logging.getLogger(__name__)

PdfEngine = Literal["pypdf", "pymupdf"]
PDF_ENGINES: tuple[PdfEngine, ...] = ("pypdf", "pymupdf")


@dataclass
class PdfContent:
    page_count: int  # pages in the file
    pages: list[list[Line]]  # lines of each page read; [] for a page without text
    bookmarks: list[tuple[str, int, int]]  # (title, 1-based page, depth), on pages read


def read_pdf(stream: BinaryIO, name: str, max_pages: int, engine: PdfEngine = "pypdf") -> PdfContent:
    """Read a PDF from a byte stream; ``name`` is only used in messages."""
    if engine == "pypdf":
        return _read_pypdf(stream, name, max_pages)
    if engine == "pymupdf":
        return _read_pymupdf(stream, name, max_pages)
    raise ValueError(f"unknown PDF engine {engine!r}, expected one of {PDF_ENGINES}")


# --------------------------------------------------------------------------- pypdf


def _read_pypdf(stream: BinaryIO, name: str, max_pages: int) -> PdfContent:
    try:
        reader = PdfReader(stream, strict=False)
    except (PdfReadError, OSError, ValueError) as exc:
        raise LoaderError(f"{name}: unreadable PDF: {exc}") from exc
    if reader.is_encrypted:
        try:
            decrypted = reader.decrypt("")  # many PDFs are "encrypted" with an empty password
        except Exception:
            decrypted = 0
        if not decrypted:
            raise LoaderError(f"{name}: encrypted PDF")

    pages: list[list[Line]] = []
    for number, page in enumerate(reader.pages[:max_pages], start=1):
        try:
            pages.append(page_lines(page, number))
        except Exception:  # one broken page must not lose the document
            logger.warning("%s: page %d could not be read", name, number, exc_info=True)
            pages.append([])
    return PdfContent(len(reader.pages), pages, _pypdf_bookmarks(reader, len(pages)))


def _pypdf_bookmarks(reader: PdfReader, max_page: int) -> list[tuple[str, int, int]]:
    result: list[tuple[str, int, int]] = []

    def walk(items: list, depth: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, depth + 1)  # children follow their parent entry
                continue
            try:
                page = reader.get_destination_page_number(item) + 1
            except Exception:  # broken destinations are common; skip the entry
                continue
            if 1 <= page <= max_page:
                result.append((str(item.title), page, depth))

    try:
        walk(reader.outline, 1)
    except Exception:  # an unreadable outline only costs us a signal
        return []
    return result


# --------------------------------------------------------------------------- PyMuPDF


def _read_pymupdf(stream: BinaryIO, name: str, max_pages: int) -> PdfContent:
    try:
        import pymupdf
    except ImportError as exc:
        raise LoaderError("PyMuPDF is not installed: use engine='pypdf'") from exc
    try:
        doc = pymupdf.open(stream=stream.read(), filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several error types on corrupt files
        raise LoaderError(f"{name}: unreadable PDF: {exc}") from exc
    with doc:
        if doc.needs_pass and not doc.authenticate(""):
            raise LoaderError(f"{name}: encrypted PDF")
        pages: list[list[Line]] = []
        for number, page in enumerate(doc.pages(0, min(max_pages, doc.page_count)), start=1):
            try:
                pages.append(_mupdf_page_lines(page, number))
            except Exception:
                logger.warning("%s: page %d could not be read", name, number, exc_info=True)
                pages.append([])
        bookmarks = [
            (title, page, level)
            for level, title, page, *_ in doc.get_toc(simple=True)
            if 1 <= page <= len(pages)
        ]
        return PdfContent(doc.page_count, pages, bookmarks)


def _mupdf_page_lines(page: object, page_no: int) -> list[Line]:
    """One piece per span, in drawing order; lines are rebuilt like pypdf's.

    PyMuPDF's own "lines" split a visual line at large gaps ("1" | "Introduction"),
    so only its spans are used. Bold and italic come from the font name, as with
    pypdf: PyMuPDF's bold flag also covers medium weights (author names, table headers).
    """
    height = page.rect.height or 1.0
    pieces: list[Piece] = []
    for block in page.get_text("dict")["blocks"]:
        for raw in block.get("lines", []):
            dx, dy = raw["dir"]
            for span in raw["spans"]:
                if not span["text"]:
                    continue
                bold, italic = font_style(span["font"])
                x0, _, x1, _ = span["bbox"]
                pieces.append(Piece(
                    text=span["text"],
                    x=x0,
                    y=height - span["origin"][1],  # PyMuPDF's y points down
                    size=span["size"],
                    width=x1 - x0,
                    bold=bold,
                    italic=italic,
                    upright=abs(dy) <= ROTATION_TOLERANCE * abs(dx),
                ))
    return lines_from_pieces(pieces, page_no, height, page.rect.width or 1.0)
