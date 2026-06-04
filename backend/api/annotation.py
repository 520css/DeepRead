"""API routes for paper annotations (standalone notes, separate from highlights)."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from data.db import PaperDB

router = APIRouter(prefix="/api/annotation", tags=["annotation"])


class CreateAnnotationRequest(BaseModel):
    paper_id: int
    content: str
    highlights: Optional[List[int]] = None  # linked highlight IDs (legacy, array form)
    highlight_id: Optional[int] = None      # frontend sends singular form
    tags: Optional[List[str]] = None


class UpdateAnnotationRequest(BaseModel):
    content: Optional[str] = None
    tags: Optional[List[str]] = None


@router.get("")
async def get_annotations(paper_id: int = Query(..., description="Paper ID")):
    """Get all annotations for a paper (query param)."""
    return await _get_annotations(paper_id)


@router.get("/{paper_id}")
async def get_annotations_by_path(paper_id: int):
    """Get all annotations for a paper (path param — frontend compatibility)."""
    return await _get_annotations(paper_id)


async def _get_annotations(paper_id: int):
    db = PaperDB()
    try:
        notes = db.get_notes_by_paper(paper_id)
        return [_format_note(n) for n in notes]
    finally:
        db.close()


@router.post("")
async def create_annotation(body: CreateAnnotationRequest):
    """Create a new annotation for a paper."""
    db = PaperDB()
    try:
        # Merge singular highlight_id into highlights array for storage
        highlight_ids = body.highlights or []
        if body.highlight_id and body.highlight_id not in highlight_ids:
            highlight_ids.append(body.highlight_id)

        note_id = db.add_note(
            paper_id=body.paper_id,
            content=body.content,
            highlights=highlight_ids if highlight_ids else None,
            tags=body.tags,
        )
        # Read back the full record so the frontend gets all fields
        row = db.conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row:
            return _format_note(dict(row))
        return {"id": note_id, "status": "created", "highlight_id": str(body.highlight_id) if body.highlight_id else None}
    finally:
        db.close()


@router.patch("/{annotation_id}")
async def update_annotation(annotation_id: int, body: UpdateAnnotationRequest):
    """Update an annotation's content or tags."""
    db = PaperDB()
    try:
        # Direct update via SQLite
        if body.content is not None:
            db.conn.execute(
                "UPDATE notes SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (body.content, annotation_id)
            )
        if body.tags is not None:
            import json
            db.conn.execute(
                "UPDATE notes SET tags = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(body.tags), annotation_id)
            )
        db.conn.commit()
        # Return the full updated record
        row = db.conn.execute("SELECT * FROM notes WHERE id = ?", (annotation_id,)).fetchone()
        if row:
            return _format_note(dict(row))
        return {"id": annotation_id, "status": "updated"}
    finally:
        db.close()


@router.delete("/{annotation_id}")
async def delete_annotation(annotation_id: int):
    """Delete an annotation."""
    db = PaperDB()
    try:
        db.conn.execute("DELETE FROM notes WHERE id = ?", (annotation_id,))
        db.conn.commit()
        return {"status": "deleted"}
    finally:
        db.close()


def _format_note(note: dict) -> dict:
    import json
    highlights = json.loads(note.get("highlights", "[]")) if note.get("highlights") else []
    return {
        "id": str(note.get("id", "")),
        "paper_id": str(note.get("paper_id", "")),
        "content": note.get("content", ""),
        "highlights": highlights,
        "highlight_id": str(highlights[0]) if highlights else None,
        "tags": json.loads(note.get("tags", "[]")) if note.get("tags") else [],
        "role": "user",
        "created_at": str(note.get("created_at", "")),
        "updated_at": str(note.get("updated_at", "")),
    }
