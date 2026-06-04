"""API routes for paper tag management."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from data.db import PaperDB

router = APIRouter(prefix="/api/paper/tag", tags=["tag"])


class CreateTagRequest(BaseModel):
    name: str


class BulkTagRequest(BaseModel):
    paper_ids: List[int]
    tag: str


@router.get("/")
async def list_tags(paper_id: Optional[int] = Query(None)):
    """List tags (optionally filtered by paper). Keywords stored in papers table serve as tags."""
    db = PaperDB()
    try:
        if paper_id:
            paper = db.get_paper(paper_id)
            if not paper:
                return []
            keywords = paper.get("keywords", "")
            return [k.strip() for k in keywords.split(",") if k.strip()]

        # Global: collect all unique keywords
        papers = db.list_papers()
        all_tags = set()
        for p in papers:
            kw = p.get("keywords", "")
            for t in kw.split(","):
                t = t.strip()
                if t:
                    all_tags.add(t)
        return sorted(all_tags)
    finally:
        db.close()


@router.post("/")
async def add_tag(paper_id: int = Query(...), tag: str = Query(...)):
    """Add a tag to a paper (appends to keywords field)."""
    db = PaperDB()
    try:
        paper = db.get_paper(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")

        existing = paper.get("keywords", "")
        tags = [t.strip() for t in existing.split(",") if t.strip()]
        if tag.strip() not in tags:
            tags.append(tag.strip())
        new_keywords = ", ".join(tags)

        db.update_paper_metadata(paper_id, keywords=new_keywords)
        db.set_user_modified(paper_id, True)
        return {"paper_id": paper_id, "tags": tags}
    finally:
        db.close()


@router.post("/bulk")
async def bulk_tag(body: BulkTagRequest):
    """Add a tag to multiple papers at once."""
    db = PaperDB()
    try:
        for pid in body.paper_ids:
            paper = db.get_paper(pid)
            if not paper:
                continue
            existing = paper.get("keywords", "")
            tags = [t.strip() for t in existing.split(",") if t.strip()]
            if body.tag.strip() not in tags:
                tags.append(body.tag.strip())
            db.update_paper_metadata(pid, keywords=", ".join(tags))
        db.conn.commit()
        return {"status": "ok", "tagged": len(body.paper_ids)}
    finally:
        db.close()


@router.delete("/papers/{paper_id}/tags/{tag_name}")
async def remove_tag(paper_id: int, tag_name: str):
    """Remove a tag from a paper."""
    db = PaperDB()
    try:
        paper = db.get_paper(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")

        existing = paper.get("keywords", "")
        tags = [t.strip() for t in existing.split(",") if t.strip()]
        tags = [t for t in tags if t != tag_name]
        new_keywords = ", ".join(tags)

        db.update_paper_metadata(paper_id, keywords=new_keywords)
        return {"paper_id": paper_id, "tags": tags}
    finally:
        db.close()
