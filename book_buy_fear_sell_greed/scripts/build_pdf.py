"""Gera o PDF do guia a partir do Markdown, sem reproduzir o livro."""
from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "guia_tecnico.md"
TARGET = ROOT / "docs" / "guia_tecnico.pdf"


def inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", text)
    text = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", text)
    return text


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(2 * cm, 1.1 * cm, "Guia técnico independente — uso educacional")
    canvas.drawRightString(A4[0] - 2 * cm, 1.1 * cm, f"Página {doc.page}")
    canvas.restoreState()


def main() -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleCustom", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=25, leading=30, textColor=colors.HexColor("#0f172a"), alignment=TA_CENTER, spaceAfter=18))
    styles.add(ParagraphStyle(name="H1Custom", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=colors.HexColor("#0f4c81"), spaceBefore=14, spaceAfter=8))
    styles.add(ParagraphStyle(name="H2Custom", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=colors.HexColor("#1e3a5f"), spaceBefore=10, spaceAfter=5))
    styles.add(ParagraphStyle(name="BodyCustom", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=14, textColor=colors.HexColor("#1f2937"), spaceAfter=7))
    styles.add(ParagraphStyle(name="BulletCustom", parent=styles["BodyCustom"], leftIndent=14, firstLineIndent=-9, bulletIndent=4))
    story = []
    first = True
    for raw in SOURCE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            story.append(Spacer(1, 3))
        elif line.startswith("# "):
            if not first:
                story.append(PageBreak())
            story.append(Paragraph(inline(line[2:]), styles["TitleCustom"]))
            first = False
        elif line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), styles["H1Custom"]))
        elif line.startswith("### "):
            story.append(Paragraph(inline(line[4:]), styles["H2Custom"]))
        elif re.match(r"^\d+\. ", line):
            story.append(Paragraph(inline(line), styles["BulletCustom"]))
        elif line.startswith("- "):
            story.append(Paragraph("• " + inline(line[2:]), styles["BulletCustom"]))
        else:
            story.append(Paragraph(inline(line), styles["BodyCustom"]))
    doc = SimpleDocTemplate(str(TARGET), pagesize=A4, rightMargin=2 * cm, leftMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm, title="Comprar o medo, vender a ganância — guia técnico independente", author="Projeto RSI2")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(TARGET)


if __name__ == "__main__":
    main()
