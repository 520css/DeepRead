"""API routes for paper CRUD."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from adapters.storage_adapter import paper_to_frontend, paper_list_to_frontend
from services.paper_service import PaperService

router = APIRouter(prefix="/api/paper", tags=["paper"])


class PaperUpdateRequest(BaseModel):
    title: Optional[str] = None
    authors: Optional[str] = None
    year: Optional[int] = None
    abstract: Optional[str] = None
    keywords: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None


# ★ Static routes must come before parameterized routes

@router.get("/all")
async def list_papers(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200)):
    """List all papers with pagination."""
    svc = PaperService()
    try:
        papers = svc.list_papers()
        start = (page - 1) * limit
        end = start + limit
        page_papers = papers[start:end]
        return {
            "papers": paper_list_to_frontend(page_papers),
            "total": len(papers),
            "page": page,
            "limit": limit,
        }
    finally:
        svc.close()


@router.get("/active")
@router.get("/relevant")
async def active_papers():
    """Get recently active/relevant papers."""
    svc = PaperService()
    try:
        papers = svc.list_papers()[:20]
        return {"papers": paper_list_to_frontend(papers)}
    finally:
        svc.close()


@router.get("/conversation")
async def get_paper_conversation(paper_id: int = Query(...)):
    """Get or create a conversation for a paper (frontend compatibility)."""
    from data.db import PaperDB
    db = PaperDB()
    try:
        convs = db.list_conversations(paper_id)
        if convs:
            return {"id": str(convs[0]["id"]), "paper_id": str(paper_id)}
        # Auto-create if none exists
        conv_id = db.create_conversation(paper_id, title=f"对话 - Paper #{paper_id}")
        return {"id": str(conv_id), "paper_id": str(paper_id)}
    finally:
        db.close()


@router.get("/{paper_id}")
async def get_paper(paper_id: int):
    """Get full paper details by ID (path param)."""
    return await _get_paper_by_id(paper_id)


@router.delete("")
async def delete_paper_by_query(id: int = Query(...)):
    """Delete a paper (query param)."""
    return await _delete_paper(id)


@router.delete("/{paper_id}")
async def delete_paper(paper_id: int):
    """Delete a paper (path param)."""
    return await _delete_paper(paper_id)


async def _delete_paper(paper_id: int):
    from data.db import PaperDB
    from pathlib import Path
    from data.db import PaperDB
    db = PaperDB()
    try:
        paper = db.get_paper(paper_id)
        if paper:
            # Delete PDF file
            fp = paper.get("file_path", "")
            if fp and Path(fp).exists():
                Path(fp).unlink()
            # Delete parsed cache files
            for key in ("parsed_quick_path", "parsed_verified_path"):
                pp = paper.get(key, "")
                if pp and Path(pp).exists():
                    Path(pp).unlink()
        db.conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
        db.conn.execute("DELETE FROM chunks WHERE paper_id = ?", (paper_id,))
        db.conn.execute("DELETE FROM highlights WHERE paper_id = ?", (paper_id,))
        db.conn.commit()
        return {"status": "deleted"}
    finally:
        db.close()


async def _get_paper_by_id(paper_id: int):
    svc = PaperService()
    try:
        paper = svc.get_paper(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        return paper_to_frontend(paper)
    finally:
        svc.close()


@router.get("")
async def get_paper_by_query(id: int = Query(..., description="Paper ID")):
    """Get full paper details by ID (query param — frontend compatibility)."""
    return await _get_paper_by_id(id)


@router.patch("/{paper_id}")
async def update_paper(paper_id: int, body: PaperUpdateRequest):
    """Update paper metadata. Sets user_modified=True."""
    svc = PaperService()
    try:
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        paper = svc.update_paper(paper_id, **updates)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        return paper_to_frontend(paper)
    finally:
        svc.close()


@router.post("/{paper_id}/summary")
async def generate_summary(paper_id: int):
    """Generate AI summary for a paper (stores in DB, frontend picks it up automatically)."""
    import json, re
    from pathlib import Path
    from core.llm_router import router

    svc = PaperService()
    try:
        paper = svc.get_paper(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")

        # Read parsed text
        parsed_path = paper.get("parsed_quick_path") or ""
        full_text = ""
        if parsed_path and Path(parsed_path).exists():
            data = json.loads(Path(parsed_path).read_text(encoding="utf-8"))
            full_text = data.get("full_text", "")

        if not full_text:
            raise HTTPException(status_code=400, detail="No parsed text available — upload the PDF first")

        prompt = (
            "You are a research assistant. Generate a structured Chinese summary of this paper.\n\n"
            f"Title: {paper.get('title', 'Unknown')}\n\n"
            f"Text (first 8000 chars):\n{full_text[:8000]}\n\n"
            "Output JSON (Chinese):\n"
            '{"one_liner": "一句话概括", "contributions": ["贡献1", "贡献2", "贡献3"], '
            '"method": "方法简述", "key_findings": ["发现1", "发现2"], "takeaway": "关键启示"}\n'
            "Respond ONLY with JSON, no other text."
        )

        response = ""
        async for token in router.complete(
            [{"role": "user", "content": prompt}],
            provider="deepseek", task_type="summary", max_tokens=800, max_retries=2,
        ):
            response += token

        try:
            summary_data = json.loads(response)
        except json.JSONDecodeError:
            m = re.search(r'```(?:json)?\s*([\s\S]*?)```', response)
            if m:
                try:
                    summary_data = json.loads(m.group(1))
                except json.JSONDecodeError:
                    summary_data = {"one_liner": response[:200]}
            else:
                summary_data = {"one_liner": response[:200]}

        # Format as Markdown and save to DB
        summary_md = PaperService._format_summary_markdown(summary_data, full_text)
        from data.db import PaperDB
        db = PaperDB()
        try:
            db.conn.execute("UPDATE papers SET summary = ? WHERE id = ?", (summary_md, paper_id))
            db.conn.commit()
        finally:
            db.close()

        return {"paper_id": paper_id, "summary": summary_md, "status": "generated"}
    finally:
        svc.close()


@router.get("/{paper_id}/status")
async def get_paper_status(paper_id: int):
    """Get parse status for a paper."""
    svc = PaperService()
    try:
        return svc.get_paper_status(paper_id)
    finally:
        svc.close()


@router.get("/{paper_id}/parsed")
async def get_paper_parsed(paper_id: int):
    """Get full parsed text for a paper (for right panel display)."""
    import json
    from pathlib import Path
    svc = PaperService()
    try:
        paper = svc.get_paper(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
        parsed_path = paper.get("parsed_verified_path") or paper.get("parsed_quick_path", "")
        if parsed_path and Path(parsed_path).exists():
            data = json.loads(Path(parsed_path).read_text(encoding="utf-8"))
            pages = data.get("pages", [])
            full_text = data.get("full_text", "")
            return {
                "paper_id": paper_id,
                "quality": data.get("quality", "quick"),
                "total_chars": len(full_text),
                "pages": pages,
                "full_text": full_text,
            }
        return {"paper_id": paper_id, "quality": "none", "pages": [], "full_text": ""}
    finally:
        svc.close()
