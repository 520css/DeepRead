"""API routes for PDF upload and import."""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Optional

from adapters.storage_adapter import paper_to_frontend
from services.paper_service import PaperService

router = APIRouter(prefix="/api/paper/upload", tags=["paper-upload"])


@router.post("")
async def upload_pdf(file: UploadFile = File(...), title: Optional[str] = Form(None)):
    """Upload a PDF file. Quick parse runs immediately; Verified parse runs in background.

    Returns: {job_id, paper_id, status, parse_status, chunks_indexed}
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    file_data = await file.read()
    if len(file_data) > 100 * 1024 * 1024:  # 100MB limit
        raise HTTPException(status_code=400, detail="File too large (max 100MB)")

    svc = PaperService()
    try:
        result = svc.upload_pdf(file_data, title or file.filename)

        if result.get("status") == "existing":
            return {
                "job_id": result["hash"],
                "paper_id": result["paper_id"],
                "status": "completed",
                "parse_status": result.get("parse_status"),
                "message": "Paper already exists (SHA256 matched)",
            }

        return {
            "job_id": result["hash"],
            "paper_id": result["paper_id"],
            "status": "completed",
            "parse_status": result.get("parse_status"),
            "chunks_indexed": result.get("chunks_indexed", 0),
        }
    finally:
        svc.close()


@router.get("/status/{job_id}")
async def upload_status(job_id: str):
    """Check upload job status. Since Quick parse is synchronous, always returns completed."""
    from data.db import PaperDB
    db = PaperDB()
    try:
        paper = db.get_paper_by_hash(job_id)
        paper_id = paper["id"] if paper else None
    finally:
        db.close()

    return {
        "job_id": job_id,
        "paper_id": paper_id,
        "status": "completed",
        "message": "Quick parse complete.",
    }
