"""DeepRead FastAPI entry point.

Start: uvicorn main:app --reload --port 8000
(or)  python main.py
"""

import sys
from pathlib import Path

# Ensure DeepRead/backend/ is on sys.path for absolute imports (core, agent, tools, data, etc.)
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB and warm up embedding model on startup."""
    from data.db import init_db
    init_db()
    print("[DeepRead] Database initialized")

    from services.memory_service import init_user_memory
    init_user_memory()
    print("[DeepRead] User memory initialized")

    # Warm up embedding model in background (first load is slow, ~10-30s)
    import threading
    def warmup():
        try:
            from core.embedder import get_model
            print("[DeepRead] Warming up embedding model (1.3GB, may take 10-30s)...")
            get_model()
            print("[DeepRead] Embedding model ready")
        except Exception as e:
            print(f"[DeepRead] Embedding warmup failed (will retry on first use): {e}")
    threading.Thread(target=warmup, daemon=True).start()

    yield
    print("[DeepRead] Shutting down")


app = FastAPI(
    title="DeepRead",
    description="Personal literature reading workstation — OpenPaper frontend + Paper-Assistant backend",
    version="3.0",
    lifespan=lifespan,
)

# ─── Middleware ───
from middleware.auth import NoAuthMiddleware
app.add_middleware(NoAuthMiddleware)

# CORS: allow local frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000", "http://127.0.0.1:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── API Routes ───
from api.message import router as message_router
from api.paper import router as paper_router
from api.paper_upload import router as paper_upload_router
from api.conversation import router as conversation_router
from api.highlight import router as highlight_router
from api.annotation import router as annotation_router
from api.search import router as search_router
from api.project import router as project_router
from api.tag import router as tag_router
from api.recommend import router as recommend_router
from api.discover import router as discover_router
from api.export import router as export_router
from api.stats import router as stats_router
from api.notes import router as notes_router
from api.agent import router as agent_router
from api.translate import router as translate_router

app.include_router(message_router)
app.include_router(agent_router)
app.include_router(paper_router)
app.include_router(paper_upload_router)
app.include_router(conversation_router)
app.include_router(highlight_router)
app.include_router(annotation_router)
app.include_router(search_router)
app.include_router(project_router)
app.include_router(tag_router)
app.include_router(recommend_router)
app.include_router(discover_router)
app.include_router(export_router)
app.include_router(stats_router)
app.include_router(notes_router)
app.include_router(translate_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "3.0"}


@app.get("/api/file/images/{rest:path}")
async def serve_parsed_image(rest: str):
    """Serve parsed images — supports both images/filename and images/hash/filename."""
    from fastapi.responses import FileResponse
    _root = Path(__file__).resolve().parent.parent  # DeepRead/
    path = _root / "storage" / "parsed" / "images" / rest
    if not path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path)


@app.get("/api/auth/me")
async def auth_me():
    """No-auth mode: always returns local user."""
    return {"id": "local", "email": "user@local", "name": "Local User"}


@app.get("/api/file/{paper_id}")
async def serve_pdf(paper_id: int):
    """Serve PDF file for a paper."""
    from fastapi.responses import FileResponse
    from data.db import PaperDB
    db = PaperDB()
    try:
        paper = db.get_paper(paper_id)
        if not paper or not paper.get("file_path"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="File not found")
        path = paper["file_path"]
        if not Path(path).exists():
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(path, media_type="application/pdf")
    finally:
        db.close()


# ─── Main ───
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
