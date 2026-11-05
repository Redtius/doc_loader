"""Blob parsers: a file's bytes to a Markdown Document, wherever the bytes came from.

A ``Blob`` (LangChain) carries the content with its ``path``, ``mimetype`` and
``metadata``. These parsers only convert; ``blob_loaders`` (a folder, later a DMS)
decide where content comes from.
"""

from collections.abc import Iterator
from pathlib import Path

from langchain_core.document_loaders import BaseBlobParser, Blob
from langchain_core.documents import Document

from doc_loader.blocks import pick_title, render_markdown
from doc_loader.errors import LoaderError
from doc_loader.pdf_engines import PDF_ENGINES, PdfEngine, read_pdf
from doc_loader.pdf_headings import pdf_blocks
from doc_loader.pdf_layout import drop_running_lines
from doc_loader.quality import Quality, assess
from doc_loader.word import docx_blocks

# Stored on every Document: re-index documents converted by an older loader.
LOADER_VERSION = "1.2.0"
# Pages read at most from one PDF.
MAX_PAGES = 2000

PDF_MIMETYPE = "application/pdf"
DOCX_MIMETYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_KIND_BY_MIMETYPE = {PDF_MIMETYPE: "pdf", DOCX_MIMETYPE: "docx"}
_KIND_BY_SUFFIX = {".pdf": "pdf", ".docx": "docx"}
SUPPORTED_EXTENSIONS = set(_KIND_BY_SUFFIX)


class PdfParser(BaseBlobParser):
    """One Markdown Document per PDF blob.

    ``engine``: ``"pypdf"`` (default) or ``"pymupdf"`` (optional, AGPL licence).
    ``max_pages`` limits the pages read.
    """

    def __init__(self, engine: PdfEngine = "pypdf", max_pages: int | None = None) -> None:
        if engine not in PDF_ENGINES:
            raise ValueError(f"unknown PDF engine {engine!r}, expected one of {PDF_ENGINES}")
        self.engine = engine
        self.max_pages = min(max_pages or MAX_PAGES, MAX_PAGES)

    def lazy_parse(self, blob: Blob) -> Iterator[Document]:
        name = _name(blob)
        with blob.as_bytes_io() as stream:
            content = read_pdf(stream, name, self.max_pages, self.engine)
        pages_read = len(content.pages)
        empty_pages = sum(1 for page in content.pages if not page)  # scanned or image-only
        lines = drop_running_lines([line for page in content.pages for line in page], pages_read)
        blocks = pdf_blocks(lines, content.bookmarks, content.page_count)
        title = pick_title(blocks, first_page_only=True) or _title_from(name)
        markdown = render_markdown(blocks, title)
        quality = assess(markdown, page_count=pages_read, empty_pages=empty_pages)
        yield _document(
            blob, markdown, title, quality,
            format="pdf", page_count=content.page_count, pdf_engine=self.engine,
        )


class DocxParser(BaseBlobParser):
    """One Markdown Document per Word (.docx) blob."""

    def lazy_parse(self, blob: Blob) -> Iterator[Document]:
        name = _name(blob)
        try:
            with blob.as_bytes_io() as stream:
                blocks = docx_blocks(stream)
        except Exception as exc:  # python-docx raises various errors on corrupt files
            raise LoaderError(f"{name}: unreadable Word file: {exc}") from exc
        title = pick_title(blocks, first_page_only=False) or _title_from(name)
        markdown = render_markdown(blocks, title)
        yield _document(blob, markdown, title, assess(markdown), format="docx")


class DocumentParser(BaseBlobParser):
    """Routes each blob to the PDF or Word parser, by mimetype, else by file extension."""

    def __init__(self, pdf_engine: PdfEngine = "pypdf", max_pdf_pages: int | None = None) -> None:
        self._parsers: dict[str, BaseBlobParser] = {
            "pdf": PdfParser(pdf_engine, max_pdf_pages),
            "docx": DocxParser(),
        }

    def lazy_parse(self, blob: Blob) -> Iterator[Document]:
        kind = _KIND_BY_MIMETYPE.get(blob.mimetype or "") or _KIND_BY_SUFFIX.get(Path(_name(blob)).suffix.lower())
        if kind is None:
            raise LoaderError(f"{_name(blob)}: unsupported file type ({blob.mimetype or 'unknown mimetype'})")
        yield from self._parsers[kind].lazy_parse(blob)


def _name(blob: Blob) -> str:
    return Path(blob.source).name if blob.source else "document"


def _title_from(name: str) -> str:
    return Path(name).stem.replace("_", " ").replace("-", " ").strip()


def _document(blob: Blob, markdown: str, title: str, quality: Quality, **extra: object) -> Document:
    return Document(
        page_content=markdown,
        metadata={
            **blob.metadata,  # what the blob's source knows (e.g. DMS id, version)
            "source": blob.source,
            "filename": _name(blob),
            "title": title,
            "loader_version": LOADER_VERSION,
            "quality_status": quality.status,
            "quality_reasons": "; ".join(quality.reasons),
            **extra,
        },
    )
