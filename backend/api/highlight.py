"""API routes for PDF highlights with coordinate storage."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional

from services.highlight_service import HighlightService

router = APIRouter(prefix="/api/highlight", tags=["highlight"])


class ScaledRect(BaseModel):
    x1: float = 0; y1: float = 0; x2: float = 0; y2: float = 0
    width: float = 0; height: float = 0
    pageNumber: int = 1


class ScaledPosition(BaseModel):
    boundingRect: ScaledRect = ScaledRect()
    rects: List[ScaledRect] = []
    pageNumber: int = 1


class CreateHighlightRequest(BaseModel):
    paper_id: str = ""         # frontend sends string
    position: ScaledPosition   # frontend sends "position" not "position_data"
    raw_text: str = ""         # frontend sends selected text
    page_number: int = 1
    role: str = "user"
    color: str = "yellow"
    note: str = ""


class UpdateHighlightNote(BaseModel):
    note: str


@router.get("")
async def get_highlights(paper_id: int = Query(..., description="Paper ID")):
    """Get all highlights for a paper (query param)."""
    return await _get_highlights(paper_id)


@router.get("/{paper_id}")
async def get_highlights_by_path(paper_id: int):
    """Get all highlights for a paper (path param)."""
    return await _get_highlights(paper_id)


async def _get_highlights(paper_id: int):
    svc = HighlightService()
    try:
        highlights = svc.get_highlights_by_paper(paper_id)
        return highlights
    finally:
        svc.close()


@router.post("")
async def create_highlight(body: CreateHighlightRequest):
    """Save a new highlight with PDF coordinates."""
    svc = HighlightService()
    try:
        paper_id = int(body.paper_id)
        position_dict = body.position.model_dump()
        highlight = svc.save_highlight(
            paper_id=paper_id,
            position_data=position_dict,
            note=body.note or "",
            page_number=body.page_number,
            color=body.color,
            raw_text=body.raw_text,
        )
        if not highlight:
            raise HTTPException(status_code=404, detail="Paper not found")
        return highlight
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        svc.close()


@router.delete("/{highlight_id}")
async def delete_highlight(highlight_id: int):
    """Delete a highlight by ID."""
    svc = HighlightService()
    try:
        svc.delete_highlight(highlight_id)
        return {"status": "deleted"}
    finally:
        svc.close()


@router.patch("/{highlight_id}")
async def update_highlight_note(highlight_id: int, body: UpdateHighlightNote):
    """Update the note on a highlight."""
    svc = HighlightService()
    try:
        highlight = svc.update_highlight_note(highlight_id, body.note)
        if not highlight:
            raise HTTPException(status_code=404, detail="Highlight not found")
        return highlight
    finally:
        svc.close()
