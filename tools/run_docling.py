"""Convert a PDF to Markdown with Docling (default pipeline, heading hierarchy on)."""
import sys
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

options = PdfPipelineOptions()
options.do_ocr = False  # digital PDFs: use the text layer
try:
    options.heading_hierarchy.enabled = True  # infer H1/H2/H3 (off by default)
except AttributeError:
    pass

converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
for name in sys.argv[1:]:
    path = Path(name)
    result = converter.convert(path)
    out = path.with_name(path.stem + "_docling.md")
    out.write_text(result.document.export_to_markdown(), encoding="utf-8")
    print(f"{path.name} -> {out.name}")
