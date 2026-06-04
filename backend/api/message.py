"""API routes for chat messages including streaming."""

import json
import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List

from services.chat_service import ChatService, ChatRequest

router = APIRouter(prefix="/api/message", tags=["message"])


class ChatPaperRequest(BaseModel):
    paper_id: str = ""
    user_query: str = ""
    conversation_id: str | None = None
    llm_provider: str | None = None
    model: str | None = None
    user_references: List = []


@router.post("/chat/paper")
async def chat_paper(req: ChatPaperRequest):
    chat_req = ChatRequest(
        paper_id=int(req.paper_id) if req.paper_id else 0,
        conversation_id=int(req.conversation_id) if req.conversation_id else 0,
        question=req.user_query,
        provider=req.llm_provider,
        model=req.model,
    )

    service = ChatService()

    return StreamingResponse(
        service.chat_stream(chat_req),
        media_type="text/plain",
    )


@router.get("/models")
async def get_models():
    """Return available LLM models (flat key-value format matching frontend)."""
    return {
        "models": {
            "claude-sonnet-4-6": "Claude Sonnet 4.6",
            "claude-haiku-4-5": "Claude Haiku 4.5",
            "gpt-4o-mini": "GPT-4o Mini",
            "deepseek-chat": "DeepSeek Chat",
        },
        "default": "deepseek-chat",
    }


@router.get("/{message_id}/verification")
async def get_verification(message_id: int):
    """Get hallucination verification report for a message."""
    from data.db import PaperDB
    db = PaperDB()
    try:
        return {
            "message_id": message_id,
            "status": "not_implemented",
            "message": "Verification will be implemented in M3",
        }
    finally:
        db.close()


@router.post("/{message_id}/feedback")
async def post_feedback(message_id: int, body: dict):
    """Submit hallucination feedback for a message. Triggers memory update if description given."""
    from data.db import PaperDB
    from services.memory_service import update_memory_from_feedback

    db = PaperDB()
    try:
        is_hallucination = body.get("is_hallucination", False)
        description = body.get("description", "")
        db.add_hallucination_feedback(message_id, is_hallucination, description)

        # If user provided a description, summarize it into user memory (fire-and-forget)
        if description and description.strip():
            asyncio.create_task(update_memory_from_feedback(description))

        return {"status": "ok"}
    finally:
        db.close()


@router.post("/chat/everything")
async def chat_everything(body: dict):
    """Cross-paper / project chat endpoint used by project conversation page."""
    from fastapi.responses import StreamingResponse
    from services.chat_service import ChatService

    project_id = body.get("project_id", 0)
    conv_id = body.get("conversation_id", 0)
    question = body.get("question", body.get("user_query", ""))

    svc = ChatService()
    if project_id:
        return StreamingResponse(
            svc.project_conversation_stream(project_id, int(conv_id) if conv_id else 0, question),
            media_type="text/plain",
        )
    else:
        return StreamingResponse(
            svc.chat_stream(body),
            media_type="text/plain",
        )


@router.post("/cancel/{conv_id}")
async def cancel_conversation(conv_id: int):
    """Cancel an active agent conversation. Returns whether cancellation was signaled."""
    cancelled = ChatService.cancel(conv_id)
    return {"cancelled": cancelled, "conv_id": conv_id}
