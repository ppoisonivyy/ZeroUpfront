"""Print the authored fictional documents using Chrome's Thai shaping and pagination."""
import html
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
CSS = """
@page{size:A4;margin:0}*{box-sizing:border-box}body{margin:0;font:13pt/1.55 Tahoma,"Noto Sans Thai",sans-serif;color:#213745}
section{height:297mm;padding:21mm 18mm;position:relative;break-after:page}
section:last-child{break-after:auto}h1{font-size:23pt;line-height:1.25;margin:9mm 0 6mm;color:#183d48}
small,footer{color:#38686b;font-size:10pt}p{margin:4.5mm 0}table{border-collapse:collapse;width:100%;margin:6mm 0;font-size:11pt}
td,th{padding:2mm;text-align:left;border-bottom:1px solid #aebfbe}th{background:#e9f2ef}footer{position:absolute;bottom:13mm}
"""


def build(path, scratch, chrome):
    title, *pages = path.read_text().strip().split("\n## ")
    sections = []
    for number, page in enumerate(pages, 1):
        heading, *lines = page.splitlines()
        body = []
        table = False
        for line in lines:
            if " | " in line:
                tag = "td" if table else "th"
                if not table:
                    body.append("<table>")
                table = True
                body.append("<tr>" + "".join(f"<{tag}>{html.escape(cell)}</{tag}>" for cell in line.split("|")) + "</tr>")
            else:
                if table:
                    body.append("</table>")
                table = False
                body.append("<p>" + html.escape(line) + "</p>")
        if table:
            body.append("</table>")
        sections.append(f"<section><small>{html.escape(title)}</small><h1>{html.escape(heading)}</h1>"
                        + "".join(body) + f"<footer>Synthetic training document · ZeroUpfront · {number} / {len(pages)}</footer></section>")
    template = scratch / "render.html"
    template.write_text('<meta charset="utf-8"><style>'+CSS+'</style>'+"".join(sections))
    subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    "--user-data-dir="+str(scratch/"profile"), "--print-to-pdf="+str(path.with_suffix(".pdf")),
                    template.as_uri()], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)


if __name__ == "__main__":
    chrome = os.getenv("CHROME_BIN") or shutil.which("chromium") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    with TemporaryDirectory() as tmp:
        for path in sorted(ROOT.glob("*.txt")):
            build(path, Path(tmp), chrome)

    # Development-only rendering of a synthetic scan. Application OCR calls Astra.
    import io
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen.canvas import Canvas
    original = ROOT/"th-case.pdf"
    reader = PdfReader(original)
    writer = PdfWriter()
    for n, page in enumerate(reader.pages, 1):
        if n == 4:
            pixels = subprocess.check_output(["pdftoppm", "-f","4","-l","4","-r","170","-gray","-singlefile","-png",str(original)])
            buffer = io.BytesIO()
            w,h = float(page.mediabox.width),float(page.mediabox.height)
            canvas = Canvas(buffer,pagesize=(w,h),invariant=1)
            canvas.drawImage(ImageReader(io.BytesIO(pixels)),0,0,w,h)
            canvas.save()
            page = PdfReader(buffer).pages[0]
        writer.add_page(page)
    writer.write(ROOT/"th-case-mixed.pdf")
