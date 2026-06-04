"""API routes for paper recommendations."""

from fastapi import APIRouter, Query
from typing import Optional, List

from adapters.storage_adapter import paper_list_to_frontend
from services.recommend_service import RecommendService

router = APIRouter(prefix="/api/recommend", tags=["recommend"])


@router.get("/similar")
async def similar_papers(paper_id: int = Query(...), limit: int = Query(5, ge=1, le=20)):
    """Get papers similar to the given paper (local library, embedding similarity)."""
    svc = RecommendService()
    try:
        results = await svc.similar_papers(paper_id, limit=limit)
        return {"papers": paper_list_to_frontend(results), "source": "local"}
    finally:
        svc.close()


@router.get("/arxiv")
async def arxiv_new_papers(
    days: int = Query(7, ge=1, le=30),
    interests: Optional[str] = Query(None, description="Comma-separated interests"),
):
    """Fetch recent arXiv papers matching interests (cached 30 min)."""
    interest_list = [i.strip() for i in interests.split(",") if i.strip()] if interests else None
    svc = RecommendService()
    try:
        results = await svc.arxiv_feed(days=days, interests=interest_list)
        return {"papers": results, "source": "arxiv", "total": len(results)}
    finally:
        svc.close()


@router.get("/forgotten")
async def forgotten_papers(limit: int = Query(10, ge=1, le=50)):
    """Get papers that haven't been read recently."""
    svc = RecommendService()
    try:
        results = await svc.forgotten_papers(limit=limit)
        return {"papers": paper_list_to_frontend(results), "source": "local", "total": len(results)}
    finally:
        svc.close()
