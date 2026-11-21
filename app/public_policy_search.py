"""Explore downloaded public wording by native text; use page OCR for damaged text."""
import argparse
import hashlib
import os
from pathlib import Path
from openai import OpenAI
from pypdf import PdfReader
from document_text import Document, Page, normalized
from policy_rag import passages, retrieve

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("question")
    parser.add_argument("--live", action="store_true", help="Embed this public policy and query using the API")
    args = parser.parse_args()
    if args.live and not os.getenv("OPENAI_API_KEY"):
        parser.error("Configure OPENAI_API_KEY in .env")
    pages = [Page(i, normalized(p.extract_text() or ""),None) for i,p in enumerate(PdfReader(args.pdf).pages,1)]
    doc = Document(args.pdf,hashlib.sha256(args.pdf.read_bytes()).hexdigest(),pages)
    chunks = passages(doc,"P")
    print(f"{len(pages)} pages, {len(chunks)} searchable native-text passages. "
          f"{sum(not p.native or chr(0xfffd) in p.native for p in pages)} pages blank or containing replacement characters.")
    for p in retrieve(args.question,chunks,OpenAI(timeout=100,max_retries=1) if args.live else None):
        print(f"p.{p.page} {p.ref} {p.text[:150]}")
