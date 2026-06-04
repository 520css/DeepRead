"""API routes for local paper search."""

from fastapi import APIRouter, Query
from adapters.storage_adapter import paper_list_to_frontend
from tools.search import search

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/local")
async def local_search(q: str = Query(..., min_length=1), scope: str = Query("global")):
    """Search local paper library by keyword (title, abstract, keywords)."""
    results = search(q, scope=scope)
    return {"results": paper_list_to_frontend(results), "query": q, "total": len(results)}
