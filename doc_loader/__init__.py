"""Turn Word and PDF documents into Markdown Documents for the RAG ingestion pipeline.

Each file becomes one LangChain ``Document``: a ``#`` title, then ``##`` / ``###``
sections that the chunker splits on. Every Document carries a quality report in its
metadata; documents marked ``rejected`` must not be indexed.

Two ways in:
- files: ``PdfLoader`` / ``DocxLoader`` (``BaseLoader``), ``load_document``,
  ``discover_documents``;
- bytes from any source: ``PdfParser`` / ``DocxParser`` / ``DocumentParser``
  (``BaseBlobParser``) on a LangChain ``Blob``, e.g. from ``FolderBlobLoader``.

PDFs are read with pypdf by default, or PyMuPDF with ``engine="pymupdf"`` /
``pdf_engine="pymupdf"`` (optional dependency, AGPL licence).
"""

from doc_loader.blob_loaders import FolderBlobLoader
from doc_loader.errors import LoaderError
from doc_loader.loaders import DocxLoader, PdfLoader, discover_documents, is_indexable, load_document
from doc_loader.parsers import (
    DOCX_MIMETYPE,
    LOADER_VERSION,
    PDF_MIMETYPE,
    SUPPORTED_EXTENSIONS,
    DocumentParser,
    DocxParser,
    PdfParser,
)
from doc_loader.pdf_engines import PDF_ENGINES

__all__ = [
    "DOCX_MIMETYPE",
    "LOADER_VERSION",
    "PDF_ENGINES",
    "PDF_MIMETYPE",
    "SUPPORTED_EXTENSIONS",
    "DocumentParser",
    "DocxLoader",
    "DocxParser",
    "FolderBlobLoader",
    "LoaderError",
    "PdfLoader",
    "PdfParser",
    "discover_documents",
    "is_indexable",
    "load_document",
]
