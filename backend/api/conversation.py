"""API routes for tree-shaped conversations."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from adapters.storage_adapter import conversation_to_frontend, message_to_frontend
from data.db import PaperDB

router = APIRouter(prefix="/api/conversation", tags=["conversation"])


class CreateConversationRequest(BaseModel):
    paper_id: int
    title: Optional[str] = None
    parent_id: Optional[int] = None
    model: Optional[str] = None


class BranchAtRequest(BaseModel):
    edit_message_index: int
    branch_reason: str = "用户分支"
    new_content: str = ""  # no longer used (chat API handles it), kept for compat


@router.post("/paper/{paper_id}")
async def create_conversation(paper_id: int, body: CreateConversationRequest = None):
    """Create a new conversation for a paper."""
    db = PaperDB()
    try:
        conv_id = db.create_conversation(
            paper_id=paper_id,
            title=(body.title if body else None) or f"对话 - Paper #{paper_id}",
            parent_id=body.parent_id if body else None,
            model=body.model if body else None,
        )
        conv = db.get_conversation(conv_id)
        return conversation_to_frontend(conv)
    finally:
        db.close()


# ── Paper-scoped routes (must be BEFORE /{conv_id}) ──

@router.get("/paper/{paper_id}/branches")
async def get_paper_branches(paper_id: int):
    """Get branch points for a paper (for the hidden branch directory)."""
    db = PaperDB()
    try:
        branches = db.get_branch_points(paper_id)
        return {
            "paper_id": paper_id,
            "branches": [conversation_to_frontend(b) for b in branches]
        }
    finally:
        db.close()


# ── Branch-at endpoint (BEFORE /{conv_id}) ──

@router.post("/{conv_id}/branch-at")
async def branch_conversation_at_endpoint(conv_id: int, body: BranchAtRequest):
    """Branch a conversation at a specific message: copy prefix only, chat API adds the edited message."""
    db = PaperDB()
    try:
        new_id = db.branch_conversation_at(
            from_conv_id=conv_id,
            edit_message_index=body.edit_message_index,
            branch_reason=body.branch_reason
        )
        conv = db.get_conversation(new_id)
        return conversation_to_frontend(conv)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        db.close()


# Static routes BEFORE parameterized routes
@router.get("/everything")
async def list_all_conversations():
    """List all conversations across all papers."""
    db = PaperDB()
    try:
        papers = db.list_papers()
        all_convs = []
        for p in papers:
            convs = db.list_conversations(p["id"])
            for c in convs:
                all_convs.append(conversation_to_frontend(c))
        return {"conversations": all_convs}
    finally:
        db.close()


@router.get("/{conv_id}")
async def get_conversation(conv_id: int, page: int = Query(1, ge=1)):
    """Get conversation with message history."""
    db = PaperDB()
    try:
        conv = db.get_conversation(conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = db.get_messages(conv_id)
        per_page = 50
        start = (page - 1) * per_page
        page_messages = messages[start:start + per_page]

        # Get children for forward navigation
        children = db.get_conversation_children(conv_id)

        return {
            "conversation": conversation_to_frontend(conv),
            "messages": [message_to_frontend(m) for m in page_messages],
            "total_messages": len(messages),
            "page": page,
            "children": [conversation_to_frontend(c) for c in children],
        }
    finally:
        db.close()
