import importlib.util
from pathlib import Path

import pytest

from langchain_core.document_loaders import Blob

from doc_loader import (
    DOCX_MIMETYPE,
    PDF_MIMETYPE,
    DocumentParser,
    FolderBlobLoader,
    LoaderError,
    PdfLoader,
    PdfParser,
    discover_documents,
    is_indexable,
    load_document,
)
from doc_loader.pdf_headings import _numbering_rank
from doc_loader.pdf_layout import font_style

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(
    params=[
        "pypdf",
        pytest.param(
            "pymupdf",
            marks=pytest.mark.skipif(importlib.util.find_spec("pymupdf") is None, reason="PyMuPDF not installed"),
        ),
    ]
)
def engine(request):
    """Every PDF test runs with each engine."""
    return request.param


def load(name: str, engine: str = "pypdf"):
    return load_document(FIXTURES / name, pdf_engine=engine)


def headings(name: str, engine: str = "pypdf") -> list[str]:
    return [l for l in load(name, engine).page_content.splitlines() if l.startswith("#")]


def test_numbered_sections_take_levels_from_numbering(engine):
    assert headings("numbered.pdf", engine) == [
        "# Conditions generales de la carte",
        "## 1. Frais",
        "### 1.1 Frais de tenue de compte et de gestion de la carte pour les clients professionnels",
        "### 1.2 Frais de retrait",
        "## 2. Plafonds",
        "## 3. Opposition",
    ]


def test_running_header_and_footer_are_removed(engine):
    content = load("numbered.pdf", engine).page_content
    assert "Internal document" not in content
    assert "Page 1/3" not in content


def test_paragraphs_in_a_larger_font_are_not_headings(engine):
    document = load("large_paragraphs.pdf", engine)
    assert headings("large_paragraphs.pdf", engine) == ["# Guide de l'epargne", "## Livret", "## Compte a terme"]
    assert "Ce guide presente les solutions d'epargne\nproposees aux clients particuliers." in document.page_content
    assert "Le taux du livret est fixe chaque annee" in document.page_content


def test_lines_follow_reading_order_not_drawing_order(engine):
    content = load("reading_order.pdf", engine).page_content
    assert headings("reading_order.pdf", engine)[:3] == ["# Guide des cartes", "## Cartes", "### Plafonds"]
    left = [content.index(f"Colonne gauche ligne {n}") for n in range(1, 5)]
    right = [content.index(f"Colonne droite ligne {n}") for n in range(1, 5)]
    assert left == sorted(left) and right == sorted(right)  # each column top to bottom
    assert max(left) < min(right)  # the left column before the right one


def test_margins_are_measured_on_the_visible_page(engine):
    content = load("cropped.pdf", engine).page_content
    assert "Internal document" not in content
    assert "Page 1/3" not in content
    assert "Section 2" in content


def test_bookmarks_give_levels_when_style_cannot(engine):
    assert headings("bookmarks.pdf", engine) == ["# Guide epargne", "## Livret", "### Taux", "## Compte a terme"]


def test_price_list_lines_stay_content(engine):
    document = load("tariffs.pdf", engine)
    assert headings("tariffs.pdf", engine) == ["# Grille tarifaire", "## Cartes"]
    for item in ["Carte Gold 300", "Opposition 50", "Frais de tenue de compte 25"]:
        assert item in document.page_content


def test_table_of_contents_lines_are_not_headings(engine):
    assert headings("toc.pdf", engine) == [
        "# Guide du client",
        "## Sommaire",
        "## Comptes", "## Cartes", "## Credits", "## Epargne", "## Assurances", "## Contacts",
    ]


def test_rotated_text_is_never_a_heading(engine):
    assert headings("rotated.pdf", engine) == ["# Fiche produit", "## Description"]


def test_text_without_spaces_is_rejected(engine):
    document = load("no_spaces.pdf", engine)
    assert document.metadata["quality_status"] == "rejected"
    assert not is_indexable(document)


def test_scanned_pages_are_rejected(engine):
    document = load("scanned.pdf", engine)
    assert document.metadata["quality_status"] == "rejected"
    assert "without text" in document.metadata["quality_reasons"]


def test_engine_is_recorded(engine):
    assert load("numbered.pdf", engine).metadata["pdf_engine"] == engine


def test_unknown_engine_is_refused():
    with pytest.raises(ValueError):
        PdfLoader(FIXTURES / "numbered.pdf", engine="pdfminer")


def test_word_headings_come_from_styles_only():
    assert headings("word.docx") == [
        "# Fiche produit Assurance", "## Garanties", "### Deces", "### Invalidite", "## Tarifs",
    ]


def test_word_body_is_normalised_and_escaped():
    content = load_document(FIXTURES / "word.docx").page_content
    assert "bénéfice" in content  # "ﬁ" ligature normalised
    assert "\\#tag en debut de ligne." in content  # not a heading
    assert "Attention" in content  # bold Normal paragraph stays body text
    assert "| Base | 120 MAD |" in content


def test_metadata():
    metadata = load_document(FIXTURES / "numbered.pdf").metadata
    assert metadata["title"] == "Conditions generales de la carte"
    assert metadata["quality_status"] == "ok"
    assert metadata["loader_version"]
    assert metadata["page_count"] == 3


def test_unsupported_and_missing_files(tmp_path):
    with pytest.raises(LoaderError):
        load_document(tmp_path / "notes.txt")
    with pytest.raises(FileNotFoundError):
        discover_documents(tmp_path, single_file="missing.pdf")


def test_corrupt_pdf_is_skipped_by_discovery(tmp_path):
    (tmp_path / "broken.pdf").write_bytes(b"not a pdf")
    assert discover_documents(tmp_path) == []


@pytest.mark.parametrize(
    "name, expected",
    [
        ("ABCDEF+Arial-BoldMT", (True, False)),
        ("TimesNewRomanPS-BoldItalicMT", (True, True)),
        ("Helvetica-Oblique", (False, True)),
        ("HelveticaNeue-SemiBold", (True, False)),
        ("Foo-Bd", (True, False)),
        ("Avenir-Book", (False, False)),
        ("LinLibertineTB", (False, False)),
    ],
)
def test_font_style(name, expected):
    assert font_style(name) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Chapitre 2 Les cartes", 1),
        ("Article 3 Resiliation", 2),
        ("II. Frais", 3),
        ("1. Frais", 4),
        ("1.2 Frais de retrait", 5),
        ("A. Champ", 8),
        ("a) local", 9),
        ("2024 Rapport annuel", None),
        ("Frais", None),
    ],
)
def test_numbering_rank(text, expected):
    assert _numbering_rank(text) == expected


# --------------------------------------------------------------------------- blob parsers


def test_pdf_parser_reads_bytes_like_the_file_loader(engine):
    data = (FIXTURES / "numbered.pdf").read_bytes()
    blob = Blob.from_data(data, mime_type=PDF_MIMETYPE, metadata={"source": "dms://docs/42", "dms_version": 3})
    from_bytes = PdfParser(engine).parse(blob)[0]
    from_file = load("numbered.pdf", engine)
    assert from_bytes.page_content == from_file.page_content
    assert from_bytes.metadata["source"] == "dms://docs/42"
    assert from_bytes.metadata["dms_version"] == 3  # what the source knows is kept


def test_document_parser_routes_by_mimetype_without_extension():
    data = (FIXTURES / "word.docx").read_bytes()
    blob = Blob.from_data(data, mime_type=DOCX_MIMETYPE, metadata={"source": "dms://docs/7"})
    assert DocumentParser().parse(blob)[0].metadata["format"] == "docx"


def test_document_parser_refuses_unknown_types():
    with pytest.raises(LoaderError):
        DocumentParser().parse(Blob.from_data(b"hello", mime_type="text/plain", path="notes.txt"))


def test_folder_blob_loader_yields_supported_files_only(tmp_path):
    (tmp_path / "cartes").mkdir()
    (tmp_path / "cartes" / "fiche.pdf").write_bytes((FIXTURES / "tariffs.pdf").read_bytes())
    (tmp_path / "notes.txt").write_text("ignored")
    names = [Path(blob.path).name for blob in FolderBlobLoader(tmp_path).yield_blobs()]
    assert names == ["fiche.pdf"]
    assert discover_documents(tmp_path)[0][0] == "cartes"


def test_positions_outside_the_page_keep_drawing_order():
    from doc_loader.pdf_layout import Piece, lines_from_pieces
    from doc_loader.quality import assess

    def piece(text, y):
        return Piece(text=text, x=50, y=y, size=10, width=60, bold=False, italic=False, upright=True)

    # An engine reporting y in another space (e.g. 2,400 on an 800-point page), upside down.
    lines = lines_from_pieces([piece("first", 600), piece("second", 1500), piece("third", 2400)], 1, 800, 600)
    assert [line.text for line in lines] == ["first", "second", "third"]  # not re-sorted by y
    assert not any(line.positioned for line in lines)
    report = assess("# t\n\ntext", page_count=1, unpositioned_pages=1)
    assert report.status == "warning" and "drawing order kept" in "; ".join(report.reasons)
