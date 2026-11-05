# doc-loader

Turns Word (`.docx`) and PDF files into Markdown LangChain `Document`s for retrieval-augmented generation (RAG): a `#` title, then `##` / `###` sections a chunker can split on, and a quality report so badly extracted documents are not indexed silently.

## What it does

- **Word**: headings from styles (built-in `Title` / `Heading N`, or any style with an outline level), tables as Markdown tables.
- **PDF**: lines rebuilt from the position of each piece of text (robust to PDFs whose own line breaks are wrong), then headings from:
  1. the PDF bookmarks, when present;
  2. otherwise font size and weight, with numbering (`I.` > `1.` > `1.1` > `A.`) to separate headings that share a style.

  Running headers and footers, rotated text (stamps, watermarks) and table-of-contents lines are not treated as headings.
- **Quality report** on every document (`quality_status`: `ok` / `warning` / `rejected`): words run together (lost spaces), undecoded characters, pages without text (scanned), tables read column by column, no headings.
- **Two PDF engines**: `pypdf` (default) or `pymupdf` (optional; note that PyMuPDF is AGPL-3.0 or commercially licensed).

## Usage

```python
from doc_loader import PdfLoader, load_document, discover_documents, is_indexable

doc = load_document("guide.pdf")                       # or .docx
doc = next(PdfLoader("guide.pdf", engine="pymupdf").lazy_load())

for category, doc in discover_documents("incoming/"):  # category = sub-folder
    if is_indexable(doc):
        ...
```

Bytes from any source (a document management system, object storage...) go through the blob parsers:

```python
from langchain_core.document_loaders import Blob
from doc_loader import DocumentParser

blob = Blob.from_data(content, mime_type="application/pdf", metadata={"source": "dms://docs/42"})
doc = DocumentParser().parse(blob)[0]
```

Command line:

```bash
python run.py out/ [--engine pypdf|pymupdf] file.pdf other.pdf:50   # :50 = first 50 pages
```

## Layout

| Path | Role |
|---|---|
| `doc_loader/parsers.py` | `PdfParser`, `DocxParser`, `DocumentParser` (LangChain `BaseBlobParser`) |
| `doc_loader/loaders.py` | `PdfLoader`, `DocxLoader` (`BaseLoader`), `load_document`, `discover_documents` |
| `doc_loader/blob_loaders.py` | `FolderBlobLoader` |
| `doc_loader/pdf_engines.py` | reading a PDF with pypdf or PyMuPDF |
| `doc_loader/pdf_layout.py` | text pieces to lines; running headers and footers; font style |
| `doc_loader/pdf_headings.py` | headings and levels |
| `doc_loader/word.py` | Word documents |
| `doc_loader/quality.py` | quality report |
| `tests/` | tests and their synthetic fixtures (`make_fixtures.py` regenerates them; needs `reportlab`) |
| `tools/chunking_experiment.py` | compares splitting on titles with splitting by size only |
| `tools/run_docling.py` | converts PDFs with Docling, for comparison |

## Tests

```bash
pip install -e ".[test]"        # add [pymupdf] to also test the PyMuPDF engine
pytest
```

## Credits

The heading-level logic (bookmarks, then numbering, then style) and the font-name parsing are adapted from [Docling](https://github.com/docling-project/docling) (MIT licence, Copyright The Docling Contributors).
