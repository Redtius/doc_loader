"""Convert documents with doc_loader and write their Markdown to an output folder.

Usage:
    python run.py <output folder> [--engine pypdf|pymupdf] <file>[:max_pages] ...
"""

import argparse
import logging
from pathlib import Path

from doc_loader import PDF_ENGINES, PdfLoader, load_document

logging.basicConfig(level=logging.ERROR)
logging.getLogger("pypdf").setLevel(logging.ERROR)

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("out_dir", type=Path)
parser.add_argument("files", nargs="+", help="file, or file:max_pages for a PDF")
parser.add_argument("--engine", choices=PDF_ENGINES, default="pypdf")
args = parser.parse_args()

args.out_dir.mkdir(parents=True, exist_ok=True)
for arg in args.files:
    name, _, pages = arg.rpartition(":") if arg.rsplit(":", 1)[-1].isdigit() else (arg, "", "")
    path = Path(name)
    if pages:
        doc = next(PdfLoader(path, max_pages=int(pages), engine=args.engine).lazy_load())
    else:
        doc = load_document(path, pdf_engine=args.engine)
    (args.out_dir / f"{path.stem}.md").write_text(doc.page_content, encoding="utf-8")
    m = doc.metadata
    headings = sum(1 for line in doc.page_content.splitlines() if line.startswith("#"))
    print(f"{path.name:58} {m['quality_status']:9} {headings:3} headings  {m['quality_reasons']}")
