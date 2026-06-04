"""Storage adapter: maps SQLite rows (from PaperDB) to frontend TypeScript types.

All API routes use these functions to convert DB records before returning JSON.
"""

import json
from typing import Dict, List, Optional, Any


def paper_to_frontend(paper: dict) -> dict:
    """Convert a papers SQLite row → frontend PaperData type."""
    return {
        "id": str(paper.get("id", "")),
        "title": paper.get("title") or "",
        "authors": _parse_csv(paper.get("authors")),
        "publish_date": _year_to_date(paper.get("year")),
        "abstract": paper.get("abstract") or "",
        "keywords": _parse_csv(paper.get("keywords")),
        "doi": paper.get("doi") or "",
        "arxiv_id": paper.get("arxiv_id") or "",
        "file_url": f"http://localhost:8000/api/file/{paper.get('id')}" if paper.get("id") else "",
        "status": _map_parse_status(paper.get("parse_status")),
        "summary": paper.get("summary") or "",
        "added_at": str(paper.get("added_at", "")),
        "source": paper.get("source", "upload"),
    }


def paper_list_to_frontend(papers: List[dict]) -> List[dict]:
    """Convert a list of paper rows."""
    return [paper_to_frontend(p) for p in papers]


def highlight_to_frontend(highlight: dict) -> dict:
    """Convert a highlights SQLite row → frontend HighlightData type."""
    position_data = {}
    try:
        position_data = json.loads(highlight.get("position_data", "{}"))
    except (json.JSONDecodeError, TypeError):
        pass

    return {
        "id": str(highlight.get("id", "")),
        "paperId": str(highlight.get("paper_id", "")),
        "content": {"text": highlight.get("snippet") or ""},
        "positionData": position_data,
        "note": highlight.get("note"),
        "pageNumber": highlight.get("page_number"),
        "createdAt": str(highlight.get("created_at", "")),
    }


def highlight_list_to_frontend(highlights: List[dict]) -> List[dict]:
    """Convert a list of highlight rows."""
    return [highlight_to_frontend(h) for h in highlights]


def conversation_to_frontend(conv: dict, messages: List[dict] = None) -> dict:
    """Convert a conversations SQLite row → frontend ConversationData type."""
    return {
        "id": str(conv.get("id", "")),
        "paperId": str(conv.get("paper_id", "")) if conv.get("paper_id") else "",
        "parentId": str(conv.get("parent_id")) if conv.get("parent_id") else None,
        "title": conv.get("title") or "",
        "branchReason": conv.get("branch_reason") or "",
        "branchPointIndex": conv.get("branch_point_index", 0),
        "model": conv.get("model") or "",
        "messageCount": conv.get("message_count", 0),
        "createdAt": str(conv.get("created_at", "")),
        "updatedAt": str(conv.get("updated_at", "")),
    }


def message_to_frontend(msg: dict) -> dict:
    """Convert a messages SQLite row → frontend MessageData type."""
    citations = []
    try:
        citations = json.loads(msg.get("citations", "[]"))
    except (json.JSONDecodeError, TypeError):
        pass

    return {
        "id": str(msg.get("id", "")),
        "conversationId": str(msg.get("conversation_id", "")),
        "role": msg.get("role", ""),
        "content": msg.get("content", ""),
        "citations": citations,
        "model": msg.get("model") or "",
        "tokenCount": msg.get("token_count", 0),
        "costUsd": msg.get("cost_usd", 0.0),
        "feedback": msg.get("feedback"),
        "guardResult": msg.get("guard_result", ""),
        "createdAt": str(msg.get("created_at", "")),
    }


# ─── Helpers ───

def _parse_csv(val: Optional[str]) -> List[str]:
    if not val:
        return []
    return [a.strip() for a in val.split(",") if a.strip()]


def _year_to_date(year) -> str:
    if not year:
        return ""
    return str(year)


def _map_parse_status(status: Optional[str]) -> str:
    """Map internal parse_status to frontend PaperStatus enum values."""
    mapping = {
        "pending": "processing",
        "quick": "ready",
        "verified": "ready",
        "failed": "error",
    }
    return mapping.get(status, "processing")
