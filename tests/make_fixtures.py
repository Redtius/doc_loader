"""Generate the test documents in tests/fixtures (run once; the outputs are committed).

Requires reportlab and python-docx. Each fixture isolates one case the loader must
handle; none is a copy of a real document.
"""

from pathlib import Path

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "fixtures"
WIDTH, HEIGHT = A4
LEADING = 1.25  # line spacing, in font sizes
BODY = "Le client peut consulter ses comptes et suivre ses opérations à tout moment depuis son agence."


class Page:
    """Writes lines top-down on a reportlab canvas."""

    def __init__(self, c: canvas.Canvas, top: float = HEIGHT - 80) -> None:
        self.c, self.y = c, top

    def line(self, text: str, size: float = 10, bold: bool = False, gap_after: float = 0) -> float:
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        self.c.drawString(60, self.y, text)
        y = self.y
        self.y -= size * LEADING + gap_after
        return y


def running(c: canvas.Canvas, number: int, total: int) -> None:
    c.setFont("Helvetica", 8)
    c.drawString(60, HEIGHT - 30, "Example Corp - Internal document")
    c.drawString(WIDTH - 110, 25, f"Page {number}/{total}")


def numbered() -> None:
    """Numbered sections, a wrapped sub-heading, a bold sub-heading, running header/footer."""
    c = canvas.Canvas(str(OUT / "numbered.pdf"), pagesize=A4)
    p = Page(c)
    running(c, 1, 3)
    p.line("Conditions generales de la carte", 20, bold=True, gap_after=10)
    p.line(BODY, gap_after=8)
    p.line("1. Frais", 14, bold=True, gap_after=4)
    p.line("1.1 Frais de tenue de compte et de gestion de la carte pour les", 11, bold=True)
    p.line("clients professionnels", 11, bold=True, gap_after=4)
    p.line(BODY, gap_after=8)
    p.line("1.2 Frais de retrait", 11, bold=True, gap_after=4)
    p.line(BODY)
    c.showPage()
    for number, heading in [(2, "2. Plafonds"), (3, "3. Opposition")]:
        p = Page(c)
        running(c, number, 3)
        p.line(heading, 14, bold=True, gap_after=4)
        p.line(BODY)
        c.showPage()
    c.save()


def cropped() -> None:
    """A visible area (crop box) smaller than the page: the running header and footer sit
    in the margins of the visible page, not of the full media box."""
    c = canvas.Canvas(str(OUT / "cropped.pdf"), pagesize=A4)
    for number in range(1, 4):
        c.setCropBox((0, 100, WIDTH, HEIGHT - 100))
        c.setFont("Helvetica", 8)
        c.drawString(60, HEIGHT - 112, "Example Corp - Internal document")
        c.drawString(WIDTH - 110, 112, f"Page {number}/3")
        p = Page(c, top=HEIGHT - 180)
        p.line(f"Section {number}", 14, bold=True, gap_after=4)
        p.line(BODY)
        c.showPage()
    c.save()


def large_paragraphs() -> None:
    """Paragraphs set in a larger font (an introduction, a bold highlight box) are not
    headings, even though their first lines are short and don't end with a period."""
    c = canvas.Canvas(str(OUT / "large_paragraphs.pdf"), pagesize=A4)
    p = Page(c)
    p.line("Guide de l'epargne", 20, bold=True, gap_after=10)
    p.line("Ce guide presente les solutions d'epargne", 14)
    p.line("proposees aux clients particuliers.", 14, gap_after=10)
    p.line("Livret", 14, bold=True, gap_after=4)
    p.line(BODY)
    p.line(BODY, gap_after=8)
    p.line("Le taux du livret est fixe chaque annee", 12, bold=True)
    p.line("et reste garanti pendant toute la duree", 12, bold=True)
    p.line("du contrat signe par le client.", 12, bold=True, gap_after=10)
    p.line("Compte a terme", 14, bold=True, gap_after=4)
    p.line(BODY)
    c.save()


def bookmarks() -> None:
    """Every heading has the same style: only the bookmarks give the levels."""
    c = canvas.Canvas(str(OUT / "bookmarks.pdf"), pagesize=A4)
    p = Page(c)
    for text, key, level in [("Guide epargne", "k0", 0), ("Livret", "k1", 1), ("Taux", "k2", 2), ("Compte a terme", "k3", 1)]:
        y = p.line(text, 12, bold=True, gap_after=4)
        c.bookmarkHorizontal(key, 0, y + 12)
        c.addOutlineEntry(text, key, level=level)
        p.line(BODY, gap_after=8)
    c.save()


def tariffs() -> None:
    """A price list: lines ending with amounts are content, not a table of contents."""
    c = canvas.Canvas(str(OUT / "tariffs.pdf"), pagesize=A4)
    p = Page(c)
    p.line("Grille tarifaire", 18, bold=True, gap_after=8)
    p.line("Cartes", 14, bold=True, gap_after=4)
    for item in ["Carte Classic 150", "Carte Gold 300", "Carte Business 450", "Carte Platinum 900",
                 "Remplacement carte 80", "Opposition 50", "Frais de tenue de compte 25"]:
        p.line(item)
    c.save()


def toc() -> None:
    """A printed table of contents in a larger font: its lines are not headings."""
    c = canvas.Canvas(str(OUT / "toc.pdf"), pagesize=A4)
    p = Page(c)
    p.line("Guide du client", 20, bold=True)
    c.showPage()
    p = Page(c)
    p.line("Sommaire", 14, bold=True, gap_after=6)
    for title, page in [("Comptes", 3), ("Cartes", 3), ("Credits", 4), ("Epargne", 4), ("Assurances", 5), ("Contacts", 5)]:
        p.line(f"{title} .......... {page}", 12)
    c.showPage()
    for titles in [["Comptes", "Cartes"], ["Credits", "Epargne"], ["Assurances", "Contacts"]]:
        p = Page(c)
        for title in titles:
            p.line(title, 14, bold=True, gap_after=4)
            p.line(BODY, gap_after=8)
        c.showPage()
    c.save()


def rotated() -> None:
    """A large vertical stamp in the margin must not become a heading."""
    c = canvas.Canvas(str(OUT / "rotated.pdf"), pagesize=A4)
    c.saveState()
    c.translate(30, 200)
    c.rotate(90)
    c.setFont("Helvetica", 24)
    c.drawString(0, 0, "COPIE - NE PAS DIFFUSER")
    c.restoreState()
    p = Page(c)
    p.line("Fiche produit", 18, bold=True, gap_after=8)
    p.line("Description", 13, bold=True, gap_after=4)
    p.line(BODY)
    c.save()


def no_spaces() -> None:
    """Text extracted without its spaces must be rejected."""
    c = canvas.Canvas(str(OUT / "no_spaces.pdf"), pagesize=A4)
    p = Page(c)
    for _ in range(6):
        p.line(BODY.replace(" ", ""))
    c.save()


def scanned() -> None:
    """Pages with no text layer must be rejected."""
    c = canvas.Canvas(str(OUT / "scanned.pdf"), pagesize=A4)
    for _ in range(2):
        c.rect(60, 300, 400, 400, fill=1)
        c.showPage()
    c.save()


def word() -> None:
    """Title style, headings, a custom style with an outline level, a bold Normal paragraph,
    a table, a ligature and a line starting with "#"."""
    d = docx.Document()
    d.add_paragraph("Fiche produit Assurance", style="Title")
    d.add_paragraph("Introduction du produit avec un bénéﬁce.")
    d.add_heading("Garanties", 1)
    d.add_heading("Deces", 2)
    d.add_paragraph("Capital verse aux beneficiaires.")
    style = d.styles.add_style("Custom Heading 2", 1)
    outline = OxmlElement("w:outlineLvl")
    outline.set(qn("w:val"), "1")
    style.element.get_or_add_pPr().append(outline)
    d.add_paragraph("Invalidite", style="Custom Heading 2")
    d.add_paragraph("Rente mensuelle.")
    d.add_paragraph().add_run("Attention").bold = True
    d.add_paragraph("#tag en debut de ligne.")
    d.add_heading("Tarifs", 1)
    table = d.add_table(rows=2, cols=2)
    for (row, col), text in {(0, 0): "Option", (0, 1): "Prime", (1, 0): "Base", (1, 1): "120 MAD"}.items():
        table.cell(row, col).text = text
    d.save(str(OUT / "word.docx"))


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for make in [numbered, cropped, large_paragraphs, bookmarks, tariffs, toc, rotated, no_spaces, scanned, word]:
        make()
    print("fixtures written to", OUT)
