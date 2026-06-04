"""Coordinate adapter: PDF position ↔ text snippet bidirectional conversion.

Maintains the dual-storage contract:
- position_data (JSON) → frontend rendering (react-pdf-highlighter)
- snippet (TEXT) → RAG retrieval, search index, LLM citations
"""

import json
from pathlib import Path
from typing import Optional


def extract_text_from_position(pdf_path: str, position_data: dict) -> str:
    """Given PDF coordinates, extract the corresponding text using PyMuPDF.

    This is called when:
    - Frontend saves a new highlight (coordinates come from react-pdf-highlighter)
    - Verified parse replaces text (coordinates unchanged, snippet re-extracted)
    """
    try:
        import fitz
    except ImportError:
        return ""

    try:
        doc = fitz.open(pdf_path)
        page_num = position_data.get("pageNumber", 1) - 1  # fitz is 0-indexed
        if page_num < 0 or page_num >= len(doc):
            doc.close()
            return ""

        page = doc[page_num]
        rects = position_data.get("rects", [])

        texts = []
        for rect in rects:
            page_rect = page.rect
            fitz_rect = fitz.Rect(
                rect.get("x1", 0) * page_rect.width,
                rect.get("y1", 0) * page_rect.height,
                rect.get("x2", 0) * page_rect.width,
                rect.get("y2", 0) * page_rect.height,
            )
            text = page.get_textbox(fitz_rect)
            if text:
                texts.append(text.strip())

        doc.close()
        return " ".join(texts)
    except Exception:
        return ""


def position_to_frontend(position_data: dict) -> dict:
    """Convert stored position JSON to react-pdf-highlighter ScaledPosition format."""
    return {
        "boundingRect": position_data.get("boundingRect", {
            "x1": 0, "y1": 0, "x2": 0, "y2": 0,
            "width": 0, "height": 0,
        }),
        "rects": position_data.get("rects", []),
        "pageNumber": position_data.get("pageNumber", 1),
    }


def frontend_to_position(scaled_position: dict) -> str:
    """Convert react-pdf-highlighter ScaledPosition → stored JSON string."""
    return json.dumps({
        "boundingRect": scaled_position.get("boundingRect", {}),
        "rects": scaled_position.get("rects", []),
        "pageNumber": scaled_position.get("pageNumber", 1),
    })


def find_chunk_position(snippet: str, chunks: list) -> Optional[dict]:
    """Given a text snippet, find its position (chunk_id, start, end) in a list of chunks.

    Used when migrating highlights from quick → verified parse.
    Returns None if not found.
    """
    for chunk in chunks:
        idx = chunk.get("content", "").find(snippet)
        if idx != -1:
            return {
                "chunk_id": chunk.get("id"),
                "snippet_start": idx,
                "snippet_end": idx + len(snippet),
            }
    return None
