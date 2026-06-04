"""API routes for the Discover page — unified search + arXiv + forgotten papers."""

from fastapi import APIRouter, Query
from typing import Optional

from adapters.storage_adapter import paper_list_to_frontend
from tools.search import search as local_search
from services.recommend_service import RecommendService

router = APIRouter(prefix="/api/discover", tags=["discover"])


@router.get("")
async def discover(
    q: str = Query("", description="Search query (local or arXiv)"),
    scope: str = Query("local", description="'local' | 'arxiv' | 'all'"),
    interests: Optional[str] = Query(None, description="Comma-separated interests for arXiv"),
    days: int = Query(7, ge=1, le=30),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    """
    Unified discover endpoint for the Discover page.
    - scope=local: searches local library
    - scope=arxiv: fetches from arXiv (cached)
    - scope=all: combines both
    Also includes forgotten papers when no query is provided.
    """
    local_results = []
    arxiv_results = []
    forgotten = []

    svc = RecommendService()
    try:
        if q and scope in ("local", "all"):
            local_results = local_search(q, scope="global")

        if scope in ("arxiv", "all"):
            interest_list = [i.strip() for i in interests.split(",") if i.strip()] if interests else None
            if not interest_list and q:
                interest_list = [q]
            arxiv_results = await svc.arxiv_feed(days=days, interests=interest_list)

        # If no query, suggest forgotten papers
        if not q:
            forgotten_raw = await svc.forgotten_papers(limit=5)
            forgotten = paper_list_to_frontend(forgotten_raw)

        return {
            "query": q,
            "scope": scope,
            "local": {
                "results": paper_list_to_frontend(local_results),
                "total": len(local_results),
            },
            "arxiv": {
                "results": arxiv_results,
                "total": len(arxiv_results),
            },
            "forgotten": forgotten,
            "page": page,
        }
    finally:
        svc.close()
