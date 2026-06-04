"""API route: general-purpose agent chat."""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List

from adapters.storage_adapter import conversation_to_frontend
from data.db import PaperDB

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentChatRequest(BaseModel):
    question: str = ""
    conversation_id: int = 0
    history: List[dict] = []


@router.get("/conversations")
async def list_agent_conversations():
    """List all agent conversations (paper_id=0)."""
    db = PaperDB()
    try:
        rows = db.conn.execute(
            "SELECT * FROM conversations WHERE paper_id = 0 ORDER BY updated_at DESC LIMIT 20"
        ).fetchall()
        return {"conversations": [conversation_to_frontend(dict(r)) for r in rows]}
    finally:
        db.close()


@router.post("/chat")
async def agent_chat(req: AgentChatRequest):
    from services.chat_service import ChatService

    svc = ChatService()
    return StreamingResponse(
        svc.agent_chat_stream(req),
        media_type="text/plain",
    )
