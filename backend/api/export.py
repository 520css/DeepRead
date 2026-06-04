"""API routes for exporting notes and conversations as Markdown."""

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import FileResponse
from typing import Optional

from services.export_service import ExportService

router = APIRouter(prefix="/api/export", tags=["export"])


@router.post("/note/{note_id}")
async def export_note(note_id: int):
    """Export a single note as Markdown file."""
    svc = ExportService()
    try:
        path = svc.export_note(note_id)
        if not path:
            raise HTTPException(status_code=404, detail="Note not found")
        return FileResponse(path, media_type="text/markdown", filename=path.name)
    finally:
        svc.close()


@router.post("/notes")
async def export_all_notes(paper_id: Optional[int] = Query(None)):
    """Export all notes (optionally filtered by paper) as a single Markdown file."""
    svc = ExportService()
    try:
        path = svc.export_all_notes(paper_id=paper_id)
        return FileResponse(path, media_type="text/markdown", filename=path.name)
    finally:
        svc.close()


@router.post("/conversation/{conv_id}")
async def export_conversation(conv_id: int):
    """Export a conversation as Markdown."""
    svc = ExportService()
    try:
        path = svc.export_conversation(conv_id)
        if not path:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return FileResponse(path, media_type="text/markdown", filename=path.name)
    finally:
        svc.close()


@router.post("/paper/{paper_id}")
async def compile_paper(paper_id: int):
    """Compile all highlights + notes for a paper into a single Markdown (Obsidian-ready)."""
    svc = ExportService()
    try:
        path = svc.compile_paper_notes(paper_id)
        if not path:
            raise HTTPException(status_code=404, detail="Paper not found")
        return FileResponse(path, media_type="text/markdown", filename=path.name)
    finally:
        svc.close()
