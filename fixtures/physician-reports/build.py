"""Render two explicitly fictional, raster-only physician reports for the demo."""

from pathlib import Path

import reportlab
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

FOLDER = Path(__file__).resolve().parent
FONT_DIR = Path(reportlab.__file__).resolve().parent / "fonts"
REGULAR = ImageFont.truetype(str(FONT_DIR / "Vera.ttf"), 25)
BOLD = ImageFont.truetype(str(FONT_DIR / "VeraBd.ttf"), 34)


def report(path, marked):
    pdf = Canvas(str(path), pagesize=A4, invariant=True)
    pdf.setTitle("Fictional treating physician report | ZU-0248")
    for number in (1, 2):
        img = Image.new("RGB", (1000, 1414), "#fffefa")
        draw = ImageDraw.Draw(img)
        draw.text((68, 60), "CANAL BRIDGE DEMO HOSPITAL", fill="#163c30", font=BOLD)
        draw.text((68, 140), "Treating physician report", fill="#172521", font=BOLD)
        draw.line([(68, 216), (930, 216)], fill="#729185", width=2)
        lines = ["Patient: Amelia Morgan", "Member: DEMO-MA-0248", "Case: ZU-0248",
                 "Admission date: 2026-11-23", "Planned procedure: Inpatient knee arthroscopy"]
        if number == 1:
            lines += ["Indication: Persistent mechanical knee symptoms.",
                      "The treating service requests planned inpatient review.",
                      "The treating physician completes the signature field on page 2."]
        else:
            lines += ["Treating physician: Dr. Mira Saran (fictional)", "Treating physician signature"]
            draw.line([(70, 745), (730, 745)], fill="#28302b", width=2)
            if marked:
                # An invented pen mark, drawn only for this fictional demonstration.
                draw.line([(115,731),(134,684),(142,723),(161,693),(162,722),(173,714),
                           (180,726),(196,709),(187,737),(199,722),(209,714),(221,720),
                           (241,704),(235,722),(260,713),(289,710)], fill="#1c365b", width=4)
        for index,line in enumerate(lines):
            draw.text((68,266+index*54),line,fill="#172521",font=REGULAR)
        draw.text((68,1290), "Fictional teaching record", fill="#52685e", font=REGULAR)
        draw.text((746,1290),f"Page {number} of 2",fill="#52685e",font=REGULAR)
        pdf.drawImage(ImageReader(img),0,0,*A4)
        pdf.showPage()
    pdf.save()


if __name__ == "__main__":
    report(FOLDER / "canal-bridge-marked.pdf", True)
    report(FOLDER / "canal-bridge-blank.pdf", False)
