"""API routes for AI-generated notes."""

import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.llm_router import router as llm_router
from data.db import PaperDB

router = APIRouter(prefix="/api/notes", tags=["notes"])


class GenerateNoteRequest(BaseModel):
    paper_id: int


@router.post("/generate")
async def generate_note(req: GenerateNoteRequest):
    """Generate structured notes for a paper using LLM + quick parsed text."""
    db = PaperDB()
    try:
        paper = db.get_paper(req.paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")

        # Read parsed text
        parsed_path = paper.get("parsed_quick_path") or paper.get("parsed_verified_path") or ""
        full_text = ""
        if parsed_path and Path(parsed_path).exists():
            data = json.loads(Path(parsed_path).read_text(encoding="utf-8"))
            full_text = data.get("full_text", "")

        if not full_text:
            raise HTTPException(status_code=400, detail="No parsed text available")

        title = paper.get("title", "Unknown")
        paper_snippet = full_text[:8000]

        prompt = (
            "You are a research assistant. Generate structured Chinese reading notes for this paper.\n\n"
            f"Title: {title}\n\n"
            f"Content (first 8000 chars):\n{paper_snippet}\n\n"
            "Generate notes in Chinese Markdown with these sections:\n"
            "## 论文概览\n- 一句话概括论文\n\n"
            "## 核心贡献\n- 贡献1\n- 贡献2\n- 贡献3\n\n"
            "## 方法\n- 简要描述研究方法\n\n"
            "## 关键发现\n- 发现1\n- 发现2\n\n"
            "## 局限与思考\n- 论文提到的局限性\n- 你的思考\n\n"
            "## 值得关注的参考文献\n- 列出2-3篇关键引用\n\n"
            "Use bullet points, keep each section concise (2-5 bullets). "
            "Respond with the Markdown directly, no JSON wrapper."
        )

        response = ""
        async for token in llm_router.complete(
            [{"role": "user", "content": prompt}],
            provider="deepseek", task_type="note", max_tokens=1200, max_retries=2,
        ):
            response += token

        return {"content": response.strip(), "paper_id": req.paper_id}
    finally:
        db.close()
