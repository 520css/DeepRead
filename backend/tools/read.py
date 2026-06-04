"""Tool: read paper content by page or via RAG."""

import json
from pathlib import Path
from typing import List, Dict

from data.db import PaperDB
from core.rag import retrieve


def read(paper_id: int, query: str = "", page: int = None) -> str:
    """Read paper content. Specify question for RAG retrieval or page for direct read."""
    db = PaperDB()
    try:
        if page is not None:
            return _read_page(db, paper_id, page)
        if query:
            chunks = retrieve(paper_id, query, top_k=15)
            if not chunks:
                return "[No relevant passages found]"
            parts = [f"[P.{ch['page_number']}] {ch['content']}" for ch in chunks]
            return "\n\n".join(parts)
        return _read_first_pages(db, paper_id)
    finally:
        db.close()


def _get_parsed_path(paper: dict) -> str:
    """Get the best available parsed file path (verified > quick)."""
    verified = paper.get("parsed_verified_path", "")
    if verified and Path(verified).exists():
        return verified
    return paper.get("parsed_quick_path", "")


def _read_page(db: PaperDB, paper_id: int, page: int) -> str:
    paper = db.get_paper(paper_id)
    if not paper:
        return "[Error: Paper not found]"
    parsed_path = _get_parsed_path(paper)
    if not parsed_path or not Path(parsed_path).exists():
        return "[Error: Parsed file not found]"
    data = json.loads(Path(parsed_path).read_text(encoding="utf-8"))
    for p in data.get("pages", []):
        if p.get("page") == page:
            return f"[P.{page}]\n{p.get('text', '')}"
    return f"[Error: Page {page} not found]"


def _read_first_pages(db: PaperDB, paper_id: int, n: int = 3) -> str:
    paper = db.get_paper(paper_id)
    if not paper:
        return "[Error: Paper not found]"
    parsed_path = _get_parsed_path(paper)
    if not parsed_path or not Path(parsed_path).exists():
        return "[Error: Parsed file not found]"
    data = json.loads(Path(parsed_path).read_text(encoding="utf-8"))
    out = []
    for p in data.get("pages", [])[:n]:
        out.append(f"[P.{p.get('page')}]\n{p.get('text', '')[:800]}")
    return "\n\n".join(out)
