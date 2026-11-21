"""Build image-only and mixed PDF variants from the committed synthetic sources."""
import io
from pathlib import Path
import subprocess

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parent


def scanned_copy(source, destination, cover=False):
    pixels = subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-singlefile", "-r",
                             "230", "-gray", "-png", str(source)],
                            check=True, capture_output=True).stdout
    packet = Canvas(str(destination), pagesize=A4, invariant=1)
    packet.setTitle("Synthetic scanned packet")
    if cover:
        packet.setFont("Helvetica-Bold", 23)
        packet.drawString(48, 735, "Policy packet")
        packet.setFont("Helvetica", 12)
        packet.drawString(48, 698, "AT-2026.1   /   Original policy wording follows on physical page 2.")
        packet.drawString(48, 55, "SYNTHETIC DEMO DOCUMENT")
        packet.showPage()
    packet.drawImage(ImageReader(io.BytesIO(pixels)), 0, 0, width=A4[0], height=A4[1])
    if cover:
        packet.drawString(60, A4[1] - 26, "Scanned enclosure")
    packet.save()


if __name__ == "__main__":
    for source, target in [("cases/Z002/estimate.pdf", "cases/Z002/scanned-estimate.pdf"),
                           ("cases/Z003/plan.pdf", "cases/Z003/scanned-plan.pdf")]:
        scanned_copy(ROOT / source, ROOT / target)
    scanned_copy(ROOT / "policies/alder.pdf", ROOT / "policies/alder-mixed.pdf", cover=True)
