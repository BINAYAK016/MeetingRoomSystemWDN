"""Build the printable handbook from the repository's Markdown guides.

Optional documentation dependency only; never imported by the application.
Run: python docs/build_handbook.py --output output/pdf/MBS_Complete_Handbook.pdf
"""

import argparse
import html
import re
import textwrap
from pathlib import Path
from urllib.parse import quote

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    HRFlowable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent.parent
NAVY = colors.HexColor("#173e67")
RED = colors.HexColor("#ed2839")
INK = colors.HexColor("#24374b")
MUTED = colors.HexColor("#627386")
PALE = colors.HexColor("#eef3f8")
LINE = colors.HexColor("#d5dfeb")
WIDTH, HEIGHT = A4
MARGIN = 19 * mm
CONTENT = WIDTH - 2 * MARGIN
SOURCES = [
    ("Start here", "docs/index.md"),
    ("Features and use cases", "docs/features-and-use-cases.md"),
    ("Employee guide", "docs/user-guide.md"),
    ("Staff guide", "docs/staff-guide.md"),
    ("Office HTTP installation", "docs/deployment-http.md"),
    ("Operations and recovery", "docs/operations-runbook.md"),
    ("Troubleshooting and logs", "docs/troubleshooting.md"),
    ("Architecture", "docs/architecture.md"),
    ("Database design", "docs/database-design.md"),
    ("Laptop setup and development", "README.md"),
    ("Verification evidence", "docs/verification-report.md"),
]


def register_fonts():
    windows = Path("C:/Windows/Fonts")
    if (windows / "times.ttf").exists():
        specs = [
            ("MbsSerif", "times.ttf"),
            ("MbsBold", "timesbd.ttf"),
            ("MbsItalic", "timesi.ttf"),
            ("MbsCode", "consola.ttf"),
        ]
        for name, file in specs:
            pdfmetrics.registerFont(TTFont(name, str(windows / file)))
        pdfmetrics.registerFontFamily(
            "MbsSerif", normal="MbsSerif", bold="MbsBold", italic="MbsItalic", boldItalic="MbsBold"
        )
        return "MbsSerif", "MbsBold", "MbsItalic", "MbsCode"
    return "Times-Roman", "Times-Bold", "Times-Italic", "Courier"


SERIF, BOLD, ITALIC, MONO = register_fonts()
STYLES = {
    "body": ParagraphStyle(
        "body", fontName=SERIF, fontSize=10.3, leading=14, textColor=INK, spaceAfter=7, splitLongWords=True
    ),
    "h1": ParagraphStyle(
        "h1",
        fontName=BOLD,
        fontSize=23,
        leading=28,
        textColor=NAVY,
        spaceBefore=3,
        spaceAfter=15,
        keepWithNext=True,
    ),
    "h2": ParagraphStyle(
        "h2",
        fontName=BOLD,
        fontSize=15,
        leading=19,
        textColor=NAVY,
        spaceBefore=13,
        spaceAfter=7,
        keepWithNext=True,
    ),
    "h3": ParagraphStyle(
        "h3",
        fontName=BOLD,
        fontSize=11.8,
        leading=15,
        textColor=NAVY,
        spaceBefore=10,
        spaceAfter=5,
        keepWithNext=True,
    ),
    "cell": ParagraphStyle(
        "cell", fontName=SERIF, fontSize=9.0, leading=11.7, textColor=INK, spaceAfter=0, splitLongWords=True
    ),
    "headercell": ParagraphStyle(
        "headercell", fontName=BOLD, fontSize=9.2, leading=12, textColor=colors.white, splitLongWords=True
    ),
    "code": ParagraphStyle(
        "code",
        fontName=MONO,
        fontSize=7.3,
        leading=9.7,
        textColor=INK,
        backColor=PALE,
        borderPadding=7,
        spaceBefore=2,
        spaceAfter=10,
    ),
    "label": ParagraphStyle(
        "label",
        fontName=BOLD,
        fontSize=8.2,
        leading=11,
        textColor=MUTED,
        spaceBefore=4,
        spaceAfter=4,
        keepWithNext=True,
    ),
    "small": ParagraphStyle("small", fontName=SERIF, fontSize=8.8, leading=12, textColor=MUTED, spaceAfter=8),
}


def normal(text):
    replacements = {
        "\u2013": "-",
        "\u2014": " - ",
        "\u2011": "-",
        "\u2010": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u2192": " -> ",
        "\u2190": " <- ",
        "\u2264": "<=",
        "\u2265": ">=",
        "\u2713": "Yes",
        "\u2717": "No",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def rich(text, source):
    text = normal(text)
    tokens = []

    def keep(markup):
        tokens.append(markup)
        return f"@@TOKEN{len(tokens) - 1}@@"

    text = re.sub(
        r"`([^`]+)`", lambda m: keep(f'<font name="{MONO}" size="8.1">{html.escape(m[1])}</font>'), text
    )

    def link(m):
        target = m[2]
        if not target.startswith(("http://", "https://")):
            if target.startswith("#"):
                path = source.relative_to(ROOT).as_posix()
            else:
                file, _, fragment = target.partition("#")
                path = (source.parent / file).resolve().relative_to(ROOT).as_posix()
                target = "#" + fragment if fragment else ""
            target = (
                "https://github.com/BINAYAK016/MeetingRoomSystemWDN/blob/mbs-prod/" + quote(path) + target
            )
        return keep(
            f'<a href="{html.escape(target, quote=True)}" color="#173e67"><u>{html.escape(m[1])}</u></a>'
        )

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    for i, token in enumerate(tokens):
        text = text.replace(f"@@TOKEN{i}@@", token)
    return text


class Handbook(BaseDocTemplate):
    def __init__(self, filename):
        super().__init__(
            str(filename),
            pagesize=A4,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=23 * mm,
            bottomMargin=20 * mm,
            title="MBS Complete Handbook",
            author="Transgate Tech | Binayak Bhandari",
        )
        self.chapter = "Meeting Booking System"
        frame = Frame(
            MARGIN,
            20 * mm,
            CONTENT,
            HEIGHT - 43 * mm,
            id="normal",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(PageTemplate(id="normal", frames=[frame], onPageEnd=self.decorate))

    def beforeDocument(self):
        self.chapter = "Contents"

    def decorate(self, canvas, doc):
        canvas.saveState()
        if doc.page > 1:
            canvas.setFillColor(NAVY)
            canvas.setFont(BOLD, 9)
            canvas.drawString(MARGIN, HEIGHT - 13 * mm, "MBS  /  Complete handbook")
            canvas.setFont(SERIF, 8.3)
            canvas.setFillColor(MUTED)
            canvas.drawRightString(WIDTH - MARGIN, HEIGHT - 13 * mm, self.chapter[:65])
            canvas.setStrokeColor(LINE)
            canvas.line(MARGIN, HEIGHT - 17 * mm, WIDTH - MARGIN, HEIGHT - 17 * mm)
        canvas.setStrokeColor(LINE)
        canvas.line(MARGIN, 16 * mm, WIDTH - MARGIN, 16 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont(SERIF, 8)
        canvas.drawString(MARGIN, 11 * mm, "Transgate Tech | Binayak Bhandari  -  Office HTTP installation")
        canvas.drawRightString(WIDTH - MARGIN, 11 * mm, str(doc.page))
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if hasattr(flowable, "toc_level"):
            level = flowable.toc_level
            label = flowable.getPlainText()
            key = flowable.bookmark_key
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(label, key, level=level, closed=True)
            self.notify("TOCEntry", (level, label, self.page, key))
            if level == 0:
                self.chapter = label


def topology(erd=False):
    drawing = Drawing(CONTENT, 190 if erd else 168)

    def box(x, y, w, title, note=""):
        drawing.add(Rect(x, y, w, 39, rx=5, ry=5, fillColor=PALE, strokeColor=LINE))
        drawing.add(
            String(x + w / 2, y + 24, title, textAnchor="middle", fontName=BOLD, fontSize=9, fillColor=NAVY)
        )
        if note:
            drawing.add(
                String(
                    x + w / 2, y + 10, note, textAnchor="middle", fontName=SERIF, fontSize=8, fillColor=MUTED
                )
            )

    def edge(x1, y1, x2, y2):
        drawing.add(Line(x1, y1, x2, y2, strokeColor=MUTED, strokeWidth=0.8))

    if not erd:
        w = 105
        box(0, 115, w, "Office browser", "HTTP port 80")
        box(155, 115, w, "Nginx proxy", "Office IP listener")
        box(310, 115, w, "Django web", "Gunicorn port 8000")
        box(310, 28, w, "PostgreSQL 17", "Internal database")
        box(155, 28, w, "Booking worker", "Lifecycle + email")
        box(0, 28, w, "Company SMTP", "Auth + booking mail")
        edge(105, 135, 155, 135)
        edge(260, 135, 310, 135)
        edge(362, 115, 362, 67)
        edge(260, 48, 310, 48)
        edge(155, 48, 105, 48)
        edge(362, 115, 52, 67)
    else:
        box(0, 140, 125, "users", "Organizer / creator")
        box(165, 140, 125, "booking_series", "Finite occurrences")
        box(330, 140, 125, "rooms", "Facilities directory")
        box(165, 75, 125, "reservations", "Meetings + closures")
        box(0, 10, 125, "booking_attendees", "Invitation recipients")
        box(165, 10, 125, "email_tokens", "Hashed challenges")
        box(330, 10, 125, "notifications", "Delivery outbox")
        edge(63, 140, 165, 95)
        edge(227, 140, 227, 114)
        edge(393, 140, 290, 95)
        edge(165, 75, 63, 49)
        edge(227, 75, 227, 49)
        edge(290, 75, 393, 49)
    return drawing


def parse(source, chapter_number, title):
    lines = source.read_text(encoding="utf-8").splitlines()
    story = []
    heading = Paragraph(f"{chapter_number}. {html.escape(title)}", STYLES["h1"])
    heading.toc_level, heading.bookmark_key = 0, f"chapter-{chapter_number}"
    story.append(heading)
    story.append(Paragraph("Source: " + source.relative_to(ROOT).as_posix(), STYLES["small"]))
    i = 0
    section = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.startswith("# "):
            i += 1
            continue
        if line.startswith("```"):
            language = line[3:].strip() or "text"
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            if language == "mermaid":
                story.extend(
                    [
                        topology(erd=any("erDiagram" in x for x in block)),
                        Paragraph(
                            "Simplified relationships/components. The linked Markdown source includes the full Mermaid diagram.",
                            STYLES["small"],
                        ),
                    ]
                )
            else:
                label = Paragraph(
                    language.upper() + "  /  Display wraps; copy complete commands from the Markdown source.",
                    STYLES["label"],
                )
                wrapped = []
                for item in block:
                    parts = textwrap.wrap(
                        normal(item),
                        width=106,
                        expand_tabs=False,
                        replace_whitespace=False,
                        drop_whitespace=False,
                        break_long_words=True,
                        break_on_hyphens=False,
                    ) or [""]
                    wrapped.extend([parts[0]] + ["    " + part for part in parts[1:]])
                story.extend([label, Preformatted("\n".join(wrapped), STYLES["code"])])
            i += 1
            continue
        if line.startswith("|"):
            # Keep the heading with the first rows without moving an entire
            # long table to the next page and leaving most of a page empty.
            if story and isinstance(story[-1], Paragraph) and story[-1].style.name == "h2":
                table_heading = story.pop()
                table_heading.style = ParagraphStyle(
                    "table_heading", parent=table_heading.style, keepWithNext=False
                )
                story.extend([CondPageBreak(150), table_heading])
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [cell.strip() for cell in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c.replace(" ", "")) for c in cells):
                    rows.append(cells)
                i += 1
            n = max(len(row) for row in rows)
            proportions = {
                2: [0.32, 0.68],
                3: [0.27, 0.38, 0.35],
                4: [0.11, 0.22, 0.25, 0.42],
                5: [0.28, 0.16, 0.16, 0.16, 0.24],
            }
            weights = proportions.get(n, [1 / n] * n)
            data = [
                [
                    Paragraph(rich(cell, source), STYLES["headercell" if row_index == 0 else "cell"])
                    for cell in row + [""] * (n - len(row))
                ]
                for row_index, row in enumerate(rows)
            ]
            table = Table(
                data,
                colWidths=[CONTENT * w for w in weights],
                repeatRows=1,
                splitByRow=True,
                splitInRow=True,
                hAlign="LEFT",
            )
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                        ("LEFTPADDING", (0, 0), (-1, -1), 7),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.extend([table, Spacer(1, 8)])
            continue
        match = re.match(r"^(#{2,6})\s+(.+)", line)
        if match:
            level = len(match[1])
            p = Paragraph(rich(match[2], source), STYLES["h2" if level == 2 else "h3"])
            if level == 2:
                section += 1
                p.toc_level, p.bookmark_key = 1, f"chapter-{chapter_number}-section-{section}"
            story.append(p)
            i += 1
            continue
        item = re.match(r"^\s*(?:([-*])\s+|(\d+)\.\s+)(.*)", line)
        if item:
            style = ParagraphStyle(
                "item", parent=STYLES["body"], leftIndent=15, firstLineIndent=0, bulletIndent=1, spaceAfter=5
            )
            text = item[3]
            bullet = item[2] + "." if item[2] else "-"
            i += 1
            while (
                i < len(lines) and lines[i].startswith("  ") and not lines[i].lstrip().startswith(("-", "*"))
            ):
                text += " " + lines[i].strip()
                i += 1
            story.append(Paragraph(rich(text, source), style, bulletText=bullet))
            continue
        paragraph = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(?:#|\||```|[-*] |\d+\. )", lines[i]):
            paragraph.append(lines[i].strip())
            i += 1
        story.append(Paragraph(rich(" ".join(paragraph), source), STYLES["body"]))
    return story


class BrandWordmark(Flowable):
    """Display the supplied wordmark, excluding its empty outer margins."""

    def __init__(self, path, width):
        super().__init__()
        self.path = str(path)
        self.width = width
        self.height = width * 86 / 876
        self.hAlign = "LEFT"

    def draw(self):
        # Same source viewport as transgate-logo.svg, with top-left PNG coords
        # converted to the PDF canvas's bottom-left coordinates.
        scale = self.width / 876
        canvas = self.canv
        canvas.saveState()
        clip = canvas.beginPath()
        clip.rect(0, 0, self.width, self.height)
        canvas.clipPath(clip, stroke=0)
        canvas.drawImage(
            self.path,
            -102 * scale,
            -(1080 - 497 - 86) * scale,
            width=1080 * scale,
            height=1080 * scale,
        )
        canvas.restoreState()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "MBS_Complete_Handbook.pdf")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc = Handbook(args.output)
    cover_style = ParagraphStyle("cover", fontName=BOLD, fontSize=35, leading=40, textColor=NAVY)
    sub_style = ParagraphStyle("cover_sub", fontName=SERIF, fontSize=17, leading=23, textColor=MUTED)
    logo_path = ROOT / "booking" / "static" / "booking" / "transgate-logo.png"
    logo = BrandWordmark(logo_path, 85 * mm)
    story = [
        Spacer(1, 28 * mm),
        logo,
        Spacer(1, 11 * mm),
        Paragraph("Meeting Booking<br/>System", cover_style),
        Spacer(1, 8 * mm),
        Paragraph("Complete handbook", sub_style),
        Spacer(1, 5 * mm),
        HRFlowable(width=CONTENT, thickness=2, color=RED),
        Spacer(1, 14 * mm),
    ]
    cover = [
        ["Employees", "Booking, recurrence, approval and check-in"],
        ["Front Desk / Administrators", "Rooms, people, policy, reports and audit"],
        ["IT / server operators", "Deployment, logs, troubleshooting and recovery"],
    ]
    cover_table = Table(
        [[Paragraph(c, STYLES["cell"]) for c in row] for row in cover],
        colWidths=[CONTENT * 0.37, CONTENT * 0.63],
    )
    cover_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.extend(
        [
            cover_table,
            Spacer(1, 15 * mm),
            Paragraph(
                "Office site: <b>http://mbs.wdn.com.np</b><br/>Oracle Linux 9.8 | PostgreSQL | Docker | Branch mbs-prod",
                STYLES["body"],
            ),
            Paragraph(
                "Documentation updated 8 October 2026, including per-room approval, invited meetings, directory suggestions and professional email. See Verification evidence for tested behavior and remaining deployment checks.",
                STYLES["small"],
            ),
            Paragraph("Transgate Tech | Binayak Bhandari", STYLES["body"]),
            PageBreak(),
        ]
    )
    story.append(Paragraph("Contents", STYLES["h1"]))
    story.append(
        Paragraph(
            "Clickable chapter/section entries and PDF bookmarks are provided. Copy terminal commands from the linked Markdown guides; long lines wrap here for print. Initial deployment and routine operation use the HTTP profile. HTTPS is a separate future option.",
            STYLES["body"],
        )
    )
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("toc0", fontName=BOLD, fontSize=11, leading=15, textColor=NAVY, spaceBefore=7),
        ParagraphStyle(
            "toc1", fontName=SERIF, fontSize=9.3, leading=12, textColor=INK, leftIndent=15, firstLineIndent=0
        ),
    ]
    story.append(toc)
    for number, (title, filename) in enumerate(SOURCES, 1):
        story.append(PageBreak())
        story.extend(parse(ROOT / filename, number, title))
    doc.multiBuild(story)
    print(f"Built {args.output} ({args.output.stat().st_size:,} bytes) from {len(SOURCES)} guides.")


if __name__ == "__main__":
    main()
