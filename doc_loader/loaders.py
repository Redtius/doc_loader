"""File-based entry points: LangChain loaders and folder discovery.

Thin wrappers that feed files to the blob parsers in ``parsers``.
"""

import logging
from collections.abc import Iterator
from pathlib import Path

from langchain_core.document_loaders import BaseLoader, Blob
from langchain_core.documents import Document

from doc_loader.blob_loaders import FolderBlobLoader
from doc_loader.errors import LoaderError
from doc_loader.parsers import DocumentParser, DocxParser, PdfParser
from doc_loader.pdf_engines import PdfEngine

logger = logging.getLogger(__name__)


class PdfLoader(BaseLoader):
    """One Markdown Document for a PDF file. See ``PdfParser`` for the options."""

    def __init__(self, path: Path, max_pages: int | None = None, engine: PdfEngine = "pypdf") -> None:
        self.path = Path(path)
        self.parser = PdfParser(engine, max_pages)

    def lazy_load(self) -> Iterator[Document]:
        yield from self.parser.lazy_parse(Blob.from_path(self.path))


class DocxLoader(BaseLoader):
    """One Markdown Document for a Word file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def lazy_load(self) -> Iterator[Document]:
        yield from DocxParser().lazy_parse(Blob.from_path(self.path))


def load_document(path: Path, pdf_engine: PdfEngine = "pypdf") -> Document:
    """Load one supported file as a single Document. Raises ``LoaderError``."""
    return next(DocumentParser(pdf_engine).lazy_parse(Blob.from_path(Path(path))))


def is_indexable(document: Document) -> bool:
    return document.metadata.get("quality_status") != "rejected"


def discover_documents(
    incoming_dir: Path,
    subfolder: str | None = None,
    single_file: str | None = None,
    pdf_engine: PdfEngine = "pypdf",
) -> list[tuple[str, Document]]:
    """``(category, document)`` pairs; the category is the sub-folder name.

    Unreadable files are logged and skipped, so one bad file doesn't stop the batch.
    Check ``is_indexable`` before indexing.
    """
    incoming_dir = Path(incoming_dir)
    if single_file:
        path = incoming_dir / single_file
        if not path.exists():
            raise FileNotFoundError(path)
        blobs: Iterator[Blob] = iter([Blob.from_path(path)])
    else:
        blobs = FolderBlobLoader(incoming_dir).yield_blobs()

    parser = DocumentParser(pdf_engine)
    results: list[tuple[str, Document]] = []
    for blob in blobs:
        category = str(Path(blob.path).parent.relative_to(incoming_dir))
        category = "general" if category == "." else category
        if subfolder and category != subfolder:
            continue
        try:
            document = next(parser.lazy_parse(blob))
        except LoaderError as exc:
            logger.error("%s", exc)
            continue
        if document.metadata["quality_status"] != "ok":
            logger.warning("%s: %s (%s)", document.metadata["filename"], document.metadata["quality_status"],
                           document.metadata["quality_reasons"])
        results.append((category, document))
    return results
