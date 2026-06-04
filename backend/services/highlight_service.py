"""Highlight service: coordinate storage, text extraction, and migration.

Architecture:
- position_data (JSON) → TRUTH SOURCE for rendering (react-pdf-highlighter)
- snippet (TEXT) → REDUNDANT copy for RAG/search (auto-extracted from coordinates)
"""

import json
from pathlib import Path
from typing import List, Optional, Dict

from data.db import PaperDB
from adapters.coordinate_adapter import (
    extract_text_from_position,
    frontend_to_position,
    position_to_frontend,
    find_chunk_position,
)

_ROOT = Path(__file__).resolve().parent.parent.parent  # paperbridge/


class HighlightService:
    """Business logic for highlight CRUD and migration."""

    def __init__(self):
        self.db = PaperDB()

    # ─── CRUD ───

    def save_highlight(
        self,
        paper_id: int,
        position_data: dict,
        note: str = "",
        source: str = "manual",
        page_number: int = 1,
        color: str = "yellow",
        raw_text: str = "",
    ) -> dict:
        """
        Save a new highlight from frontend coordinates.
        1. Extract text from PDF coordinates → snippet
        2. Store position_data + snippet in DB
        """
        paper = self.db.get_paper(paper_id)
        if not paper:
            raise ValueError(f"Paper {paper_id} not found")

        # Extract text from coordinate position in PDF
        pdf_path = paper.get("file_path", "")
        snippet = ""
        if pdf_path and Path(pdf_path).exists():
            snippet = extract_text_from_position(pdf_path, position_data)

        # Fallback: use frontend-supplied raw_text if PDF extraction failed
        if not snippet and raw_text:
            snippet = raw_text

        # Find chunk reference
        chunks = self.db.get_chunks_by_paper(paper_id)
        chunk_info = find_chunk_position(snippet, chunks)

        # Serialize position for storage
        position_json = frontend_to_position(position_data)

        highlight_id = self.db.add_highlight(
            paper_id=paper_id,
            chunk_id=chunk_info.get("chunk_id") if chunk_info else None,
            page_number=page_number,
            snippet=snippet,
            snippet_start=chunk_info.get("snippet_start") if chunk_info else None,
            snippet_end=chunk_info.get("snippet_end") if chunk_info else None,
            note=note,
            position_data=position_json,
            color=color,
        )

        return self.get_highlight(highlight_id)

    def get_highlights_by_paper(self, paper_id: int) -> List[dict]:
        """Get all highlights for a paper, formatted for frontend."""
        rows = self.db.get_highlights_by_paper(paper_id)
        return [self._format_highlight(r) for r in rows]

    def get_highlight(self, highlight_id: int) -> Optional[dict]:
        """Get a single highlight by ID."""
        row = self.db.conn.execute(
            "SELECT * FROM highlights WHERE id = ?", (highlight_id,)
        ).fetchone()
        if not row:
            return None
        return self._format_highlight(dict(row))

    def delete_highlight(self, highlight_id: int) -> bool:
        """Delete a highlight. Returns True if successful."""
        self.db.conn.execute("DELETE FROM highlights WHERE id = ?", (highlight_id,))
        self.db.conn.commit()
        return True

    def update_highlight_note(self, highlight_id: int, note: str) -> Optional[dict]:
        """Update the note on a highlight."""
        self.db.update_highlight_note(highlight_id, note)
        return self.get_highlight(highlight_id)

    # ─── Migration (Quick → Verified parse) ───

    def migrate_highlights_for_paper(self, paper_id: int) -> dict:
        """
        After verified parse completes, re-extract snippets from coordinates
        and update chunk references. Coordinates do NOT change.
        """
        paper = self.db.get_paper(paper_id)
        if not paper:
            return {"status": "error", "message": "Paper not found"}

        pdf_path = paper.get("file_path", "")
        if not pdf_path or not Path(pdf_path).exists():
            return {"status": "error", "message": "PDF file not found"}

        highlights = self.db.get_highlights_by_paper(paper_id)
        chunks = self.db.get_chunks_by_paper(paper_id)

        migrated = 0
        orphaned = 0

        for h in highlights:
            try:
                pos = json.loads(h.get("position_data", "{}"))
            except json.JSONDecodeError:
                pos = {}

            # Re-extract text from coordinates (PDF unchanged)
            new_snippet = extract_text_from_position(pdf_path, pos)
            chunk_info = find_chunk_position(new_snippet, chunks)

            if chunk_info:
                self.db.migrate_highlight(
                    h["id"],
                    chunk_id=chunk_info["chunk_id"],
                    snippet_start=chunk_info["snippet_start"],
                    snippet_end=chunk_info["snippet_end"],
                    migrated=True,
                )
                migrated += 1
            else:
                # Try embedding similarity fallback
                success = self._embedding_fallback(h, new_snippet, chunks)
                if success:
                    migrated += 1
                else:
                    self.db.orphan_highlight(h["id"])
                    orphaned += 1

        return {
            "status": "ok",
            "total": len(highlights),
            "migrated": migrated,
            "orphaned": orphaned,
        }

    def _embedding_fallback(self, highlight: dict, snippet: str, chunks: List[dict]) -> bool:
        """Fallback: use embedding similarity to find best matching chunk."""
        if not snippet or not chunks:
            return False

        try:
            from core.embedder import embed_single
            import numpy as np

            snippet_emb = embed_single(snippet)

            best_chunk = None
            best_sim = -1.0
            for c in chunks:
                chunk_emb = embed_single(c["content"])
                sim = float(np.dot(snippet_emb, chunk_emb) /
                            (np.linalg.norm(snippet_emb) * np.linalg.norm(chunk_emb) + 1e-8))
                if sim > best_sim:
                    best_sim = sim
                    best_chunk = c

            if best_chunk and best_sim > 0.85:
                # Try to find snippet start position in best chunk
                idx = best_chunk["content"].find(snippet[:30])
                self.db.migrate_highlight(
                    highlight["id"],
                    chunk_id=best_chunk["id"],
                    snippet_start=max(idx, 0) if idx >= 0 else 0,
                    snippet_end=None,
                    migrated=True,
                )
                return True
        except Exception:
            pass

        return False

    def close(self):
        self.db.close()

    # ─── Helpers ───

    def _format_highlight(self, row: dict) -> dict:
        """Format a highlight DB row for frontend, parsing position_data JSON."""
        position_data = {}
        try:
            position_data = json.loads(row.get("position_data", "{}"))
        except (json.JSONDecodeError, TypeError):
            pass

        return {
            "id": str(row.get("id", "")),
            "paper_id": str(row.get("paper_id", "")),
            "raw_text": row.get("snippet") or "",
            "position": position_to_frontend(position_data),
            "note": row.get("note"),
            "page_number": row.get("page_number"),
            "role": row.get("role") or "user",
            "color": row.get("color") or "yellow",
            "created_at": str(row.get("created_at", "")),
        }
