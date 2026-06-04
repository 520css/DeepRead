"""API routes for project management (grouping papers into projects)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import json

from data.db import PaperDB
from adapters.storage_adapter import paper_list_to_frontend

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None        # frontend sends "title"
    keywords: Optional[str] = None
    description: Optional[str] = None  # frontend sends "description"


class AddPaperRequest(BaseModel):
    paper_id: Optional[int] = None
    paper_ids: Optional[List[int]] = None


def _fmt_project(row: dict) -> dict:
    """Format project row for frontend: adds title/description aliases and role."""
    return {
        **row,
        "title": row.get("name", ""),
        "description": row.get("keywords", ""),
        "role": "admin",          # Local mode: always admin
        "num_roles": 1,
    }


@router.get("")
async def list_projects():
    """List all projects."""
    db = PaperDB()
    try:
        rows = db.conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()
        return [_fmt_project(dict(r)) for r in rows]
    finally:
        db.close()


@router.post("")
async def create_project(body: CreateProjectRequest):
    """Create a new project."""
    db = PaperDB()
    try:
        proj_name = body.name or body.title or "Untitled Project"
        proj_keywords = body.keywords or body.description or ""
        cur = db.conn.execute(
            "INSERT INTO projects (name, keywords) VALUES (?, ?)",
            (proj_name, proj_keywords)
        )
        db.conn.commit()
        return {"id": cur.lastrowid, "title": proj_name, "description": proj_keywords, "status": "created"}
    finally:
        db.close()


@router.get("/{project_id}")
async def get_project(project_id: int):
    """Get project details with associated papers."""
    db = PaperDB()
    try:
        proj = db.conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

        return _fmt_project(dict(proj))
    finally:
        db.close()


@router.delete("/{project_id}")
async def delete_project(project_id: int):
    """Delete a project."""
    db = PaperDB()
    try:
        db.conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        db.conn.commit()
        return {"status": "deleted"}
    finally:
        db.close()


@router.patch("/{project_id}")
async def update_project(project_id: int, body: CreateProjectRequest):
    """Update project name/keywords."""
    db = PaperDB()
    try:
        proj_name = body.name or body.title or ""
        proj_keywords = body.keywords or body.description or ""
        db.conn.execute(
            "UPDATE projects SET name = ?, keywords = ? WHERE id = ?",
            (proj_name, proj_keywords, project_id)
        )
        db.conn.commit()
        return {"id": project_id, "status": "updated"}
    finally:
        db.close()


# ── Invitation stubs (no-op for local single-user mode) ──

@router.get("/invitations/user")
async def user_invitations():
    return {"invitations": []}


@router.post("/invitations/{invitation_id}/accept")
async def accept_invitation(invitation_id: int):
    return {"status": "accepted"}


@router.post("/invitations/{invitation_id}/decline")
async def decline_invitation(invitation_id: int):
    return {"status": "declined"}


# ── Project papers ──

@router.get("/papers/{project_id}")
async def project_papers(project_id: int):
    db = PaperDB()
    try:
        papers = db.get_project_papers(project_id)
        return {"papers": paper_list_to_frontend(papers)}
    finally:
        db.close()


@router.post("/papers/{project_id}")
async def add_paper_to_project(project_id: int, body: dict = None):
    db = PaperDB()
    try:
        if body:
            ids = body.get("paper_ids", []) or ([body.get("paper_id")] if body.get("paper_id") else [])
            for pid in ids:
                db.add_paper_to_project(project_id, int(pid))
        return {"status": "added", "count": len(ids) if body else 0}
    finally:
        db.close()


@router.delete("/papers/{project_id}/{paper_id}")
async def remove_paper_from_project(project_id: int, paper_id: int):
    db = PaperDB()
    try:
        db.remove_paper_from_project(project_id, paper_id)
        return {"status": "removed"}
    finally:
        db.close()


@router.post("/conversations/{project_id}")
async def create_project_conversation(project_id: int, body: dict = None):
    from data.db import PaperDB
    title = body.get("title", "New Conversation") if body else "New Conversation"
    db = PaperDB()
    try:
        conv_id = db.create_conversation(0, title=title)
        db.conn.execute("UPDATE conversations SET project_id = ? WHERE id = ?", (project_id, conv_id))
        db.conn.commit()
        return {"id": conv_id, "title": title}
    finally:
        db.close()


@router.get("/conversations/{project_id}")
async def project_conversations(project_id: int):
    from data.db import PaperDB
    db = PaperDB()
    try:
        convs = db.conn.execute(
            "SELECT * FROM conversations WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,)
        ).fetchall()
        return [dict(c) for c in convs]
    finally:
        db.close()


# ── Conversation detail + messages ──

@router.get("/conversations/{project_id}/{conv_id}")
async def get_conversation_detail(project_id: int, conv_id: int):
    from data.db import PaperDB
    db = PaperDB()
    try:
        conv = db.get_conversation(conv_id)
        msgs = db.get_messages(conv_id)
        return {"conversation": dict(conv) if conv else {}, "messages": [dict(m) for m in msgs]}
    finally:
        db.close()


@router.post("/conversations/{project_id}/{conv_id}/chat")
async def project_conversation_chat(project_id: int, conv_id: int, body: dict):
    """Streaming chat in a project conversation."""
    from fastapi.responses import StreamingResponse
    from services.chat_service import ChatService
    svc = ChatService()
    return StreamingResponse(
        svc.project_conversation_stream(project_id, conv_id, body.get("question", "")),
        media_type="text/plain",
    )


# ── Collaborator stub (exit project) ──

@router.delete("/{project_id}/collaborators/self")
async def leave_project(project_id: int):
    return {"status": "left"}


# ── Project-level chat ──

@router.post("/{project_id}/chat")
async def project_chat(project_id: int, body: dict):
    """Streaming chat scoped to project papers."""
    from fastapi.responses import StreamingResponse
    from services.chat_service import ChatService

    svc = ChatService()
    return StreamingResponse(
        svc.project_chat_stream(project_id, body.get("question", "")),
        media_type="text/plain",
    )


# ── Catch-all stub: any /api/projects/* route not explicitly defined ──
# Frontend calls 25+ project sub-routes (collaborators, audio, tables, invites...)
# Single-user local mode doesn't need these — just return empty/success.

@router.get("/{project_id}/collaborators")
async def collaborator_list(project_id: int):
    return []

@router.get("/invitations/{project_id}/")
async def pending_invites(project_id: int):
    return []

@router.get("/audio/{project_id}")
async def project_audio(project_id: int):
    return []  # Frontend sets state directly

@router.get("/audio/jobs/{project_id}")
async def project_audio_jobs(project_id: int):
    return []  # Frontend sets state directly, needs .some()

@router.get("/audio/file/{project_id}/{audio_overview_id}")
async def project_audio_file(project_id: int, audio_overview_id: str):
    return {}

@router.get("/tables/jobs/{project_id}")
async def project_table_jobs(project_id: int):
    return {"jobs": []}  # Frontend expects {jobs: [...]}

@router.get("/papers/forked/{paper_id}")
async def forked_papers(paper_id: int):
    return []

@router.post("/papers/fork")
async def fork_paper():
    return {"status": "ok"}

@router.post("/invitations/{project_id}/invite")
async def invite_collaborator(project_id: int):
    return {"status": "invited"}

@router.delete("/{project_id}/collaborators/{collaborator_id}")
async def remove_collaborator(project_id: int, collaborator_id: int):
    return {"status": "removed"}

@router.post("/{project_id}/collaborators/change")
async def change_collaborator_role(project_id: int):
    return {"status": "ok"}

@router.post("/invitations/modify/{invitation_id}/retract")
@router.post("/invitations/modify/{invitation_id}/accept")
@router.post("/invitations/modify/{invitation_id}/reject")
async def modify_invitation(invitation_id: int):
    return {"status": "ok"}

@router.post("/tables/")
async def create_table():
    return {"status": "ok"}

@router.get("/tables/{job_id}")
async def get_table_job(job_id: int):
    return {}

@router.post("/audio/{project_id}")
async def create_audio_overview(project_id: int):
    return {"status": "ok"}
