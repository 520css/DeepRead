import sqlite3
import json
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).resolve().parent.parent.parent  # paperbridge/
DB_PATH = _ROOT / "storage" / "paper_assistant.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _migrate(conn):
    """Lightweight migrations for personal tool."""
    migrations = [
        ("papers", "paper_hash", "TEXT"),
        ("papers", "parse_status", "TEXT DEFAULT 'pending'"),
        ("papers", "summary", "TEXT DEFAULT ''"),
        ("conversations", "message_count", "INTEGER DEFAULT 0"),
        ("messages", "feedback", "TEXT"),
        ("messages", "guard_result", "TEXT DEFAULT ''"),
        ("highlights", "orphaned", "BOOLEAN DEFAULT FALSE"),
        ("highlights", "migrated", "BOOLEAN DEFAULT FALSE"),
        ("highlights", "position_data", "TEXT NOT NULL DEFAULT '{}'"),
        ("highlights", "source", "TEXT DEFAULT 'manual'"),
        ("highlights", "color", "TEXT DEFAULT 'yellow'"),
        ("conversations", "project_id", "INTEGER DEFAULT 0"),
        ("conversations", "branch_point_index", "INTEGER DEFAULT 0"),
    ]
    for table, column, dtype in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {dtype}")
        except sqlite3.OperationalError:
            pass
    conn.commit()


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY,
            title TEXT,
            authors TEXT,
            year INTEGER,
            abstract TEXT,
            keywords TEXT,
            doi TEXT,
            arxiv_id TEXT,
            file_path TEXT,
            parsed_quick_path TEXT,
            parsed_verified_path TEXT,
            parse_status TEXT DEFAULT 'pending',
            user_modified BOOLEAN DEFAULT FALSE,
            source TEXT DEFAULT 'upload',
            paper_hash TEXT,
            summary TEXT DEFAULT '',
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            paper_id INTEGER REFERENCES papers(id),
            page_number INTEGER,
            section TEXT,
            content TEXT,
            embedding_id TEXT
        );

        CREATE TABLE IF NOT EXISTS highlights (
            id INTEGER PRIMARY KEY,
            paper_id INTEGER REFERENCES papers(id),
            chunk_id INTEGER REFERENCES chunks(id),
            page_number INTEGER,
            snippet TEXT,
            snippet_start INTEGER,
            snippet_end INTEGER,
            position_data TEXT NOT NULL DEFAULT '{}',
            note TEXT,
            orphaned BOOLEAN DEFAULT FALSE,
            migrated BOOLEAN DEFAULT FALSE,
            source TEXT DEFAULT 'manual',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY,
            paper_id INTEGER REFERENCES papers(id),
            parent_id INTEGER REFERENCES conversations(id),
            title TEXT,
            branch_reason TEXT,
            model TEXT,
            message_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            conversation_id INTEGER REFERENCES conversations(id),
            role TEXT,
            content TEXT,
            citations TEXT,
            model TEXT,
            token_count INTEGER,
            cost_usd REAL,
            feedback TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS message_chunks (
            message_id INTEGER REFERENCES messages(id),
            chunk_id INTEGER REFERENCES chunks(id),
            PRIMARY KEY (message_id, chunk_id)
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY,
            paper_id INTEGER,
            content TEXT,
            highlights TEXT,
            tags TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS llm_usage (
            id INTEGER PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            provider TEXT,
            model TEXT,
            task_type TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cost_usd REAL,
            conversation_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS hallucination_feedback (
            id INTEGER PRIMARY KEY,
            message_id INTEGER,
            is_hallucination BOOLEAN,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            name TEXT,
            keywords TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS relations (
            paper_a_id INTEGER,
            paper_b_id INTEGER,
            similarity REAL,
            PRIMARY KEY (paper_a_id, paper_b_id)
        );

        CREATE TABLE IF NOT EXISTS project_papers (
            project_id INTEGER,
            paper_id INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (project_id, paper_id)
        );
    """)
    _migrate(conn)
    conn.close()


class PaperDB:
    def __init__(self):
        self.conn = get_conn()

    # ─── Papers ───

    def add_paper(self, title, authors, year, abstract, keywords, doi, arxiv_id,
                  file_path, parsed_quick_path, parsed_verified_path,
                  parse_status, source="upload", paper_hash=None):
        cur = self.conn.execute(
            """INSERT INTO papers (title, authors, year, abstract, keywords, doi,
                arxiv_id, file_path, parsed_quick_path, parsed_verified_path,
                parse_status, source, paper_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, authors, year, abstract, keywords, doi, arxiv_id,
             file_path, parsed_quick_path, parsed_verified_path, parse_status, source, paper_hash)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_paper(self, paper_id):
        row = self.conn.execute(
            "SELECT * FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_paper_by_hash(self, paper_hash):
        row = self.conn.execute(
            "SELECT * FROM papers WHERE paper_hash = ?", (paper_hash,)
        ).fetchone()
        return dict(row) if row else None

    def update_parse_status(self, paper_id, status, quick_path=None, verified_path=None):
        fields = ["parse_status = ?"]
        params = [status]
        if quick_path:
            fields.append("parsed_quick_path = ?")
            params.append(quick_path)
        if verified_path:
            fields.append("parsed_verified_path = ?")
            params.append(verified_path)
        params.append(paper_id)
        self.conn.execute(
            f"UPDATE papers SET {', '.join(fields)} WHERE id = ?",
            params
        )
        self.conn.commit()

    def set_user_modified(self, paper_id, modified=True):
        self.conn.execute(
            "UPDATE papers SET user_modified = ? WHERE id = ?",
            (modified, paper_id)
        )
        self.conn.commit()

    def update_paper_metadata(self, paper_id, **kwargs):
        allowed = {"title", "authors", "year", "abstract", "keywords", "doi", "arxiv_id", "paper_hash"}
        fields = []
        params = []
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                fields.append(f"{k} = ?")
                params.append(v)
        if not fields:
            return
        params.append(paper_id)
        self.conn.execute(
            f"UPDATE papers SET {', '.join(fields)} WHERE id = ?",
            params
        )
        self.conn.commit()

    def list_papers(self):
        rows = self.conn.execute(
            "SELECT * FROM papers ORDER BY added_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── Chunks ───

    def add_chunk(self, paper_id, page_number, section, content, embedding_id):
        cur = self.conn.execute(
            """INSERT INTO chunks (paper_id, page_number, section, content, embedding_id)
               VALUES (?, ?, ?, ?, ?)""",
            (paper_id, page_number, section, content, embedding_id)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_chunks_by_paper(self, paper_id):
        rows = self.conn.execute(
            "SELECT * FROM chunks WHERE paper_id = ? ORDER BY page_number",
            (paper_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_chunk_by_page(self, paper_id, page_number):
        row = self.conn.execute(
            "SELECT * FROM chunks WHERE paper_id = ? AND page_number = ?",
            (paper_id, page_number)
        ).fetchone()
        return dict(row) if row else None

    # ─── Highlights ───

    def add_highlight(self, paper_id, chunk_id, page_number, snippet, snippet_start, snippet_end, note="", position_data="{}", source="manual", color="yellow"):
        cur = self.conn.execute(
            """INSERT INTO highlights (paper_id, chunk_id, page_number, snippet, snippet_start, snippet_end, note, position_data, source, color)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (paper_id, chunk_id, page_number, snippet, snippet_start, snippet_end, note, position_data, source, color)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_highlights_by_paper(self, paper_id):
        rows = self.conn.execute(
            "SELECT * FROM highlights WHERE paper_id = ? ORDER BY page_number, snippet_start",
            (paper_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_highlight_note(self, highlight_id, note):
        self.conn.execute(
            "UPDATE highlights SET note = ? WHERE id = ?",
            (note, highlight_id)
        )
        self.conn.commit()

    def migrate_highlight(self, highlight_id, chunk_id, snippet_start, snippet_end, migrated=True):
        self.conn.execute(
            """UPDATE highlights
               SET chunk_id = ?, snippet_start = ?, snippet_end = ?, migrated = ?, orphaned = FALSE
               WHERE id = ?""",
            (chunk_id, snippet_start, snippet_end, migrated, highlight_id)
        )
        self.conn.commit()

    def orphan_highlight(self, highlight_id):
        self.conn.execute(
            "UPDATE highlights SET orphaned = TRUE WHERE id = ?",
            (highlight_id,)
        )
        self.conn.commit()

    # ─── Conversations (tree) ───

    def create_conversation(self, paper_id, title, parent_id=None, model=None):
        cur = self.conn.execute(
            """INSERT INTO conversations (paper_id, parent_id, title, model)
               VALUES (?, ?, ?, ?)""",
            (paper_id, parent_id, title, model)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_conversation(self, conv_id):
        row = self.conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_conversations(self, paper_id):
        rows = self.conn.execute(
            "SELECT * FROM conversations WHERE paper_id = ? ORDER BY updated_at DESC, created_at DESC",
            (paper_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_conversation_tree(self, paper_id):
        rows = self.conn.execute(
            "SELECT * FROM conversations WHERE paper_id = ? ORDER BY created_at",
            (paper_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def branch_conversation(self, from_conv_id, branch_reason="用户分支"):
        orig = self.get_conversation(from_conv_id)
        if not orig:
            raise ValueError("Conversation not found")
        new_id = self.create_conversation(
            paper_id=orig["paper_id"],
            title=f"{orig['title'] or '对话'} (分支)",
            parent_id=from_conv_id,
            model=orig["model"]
        )
        msgs = self.get_messages(from_conv_id)
        for m in msgs:
            self.add_message(new_id, m["role"], m["content"],
                             citations=m.get("citations"),
                             model=m.get("model"),
                             token_count=m.get("token_count"),
                             cost_usd=m.get("cost_usd"))
        self.conn.execute(
            "UPDATE conversations SET branch_reason = ? WHERE id = ?",
            (branch_reason, new_id)
        )
        self.conn.commit()
        return new_id

    def branch_conversation_at(self, from_conv_id, edit_message_index, branch_reason="用户分支"):
        """Branch at a specific message: copy prefix only (chat API adds the edited message + AI reply)."""
        orig = self.get_conversation(from_conv_id)
        if not orig:
            raise ValueError("Conversation not found")
        new_id = self.create_conversation(
            paper_id=orig["paper_id"],
            title=f"{orig['title'] or '对话'} (分支)",
            parent_id=from_conv_id,
            model=orig["model"]
        )
        msgs = self.get_messages(from_conv_id)
        # Copy messages before the edit point (NOT including the edited message itself)
        for i in range(min(edit_message_index, len(msgs))):
            m = msgs[i]
            self.add_message(new_id, m["role"], m["content"],
                             citations=m.get("citations"),
                             model=m.get("model"),
                             token_count=m.get("token_count"),
                             cost_usd=m.get("cost_usd"),
                             guard_result=m.get("guard_result", ""))
        # Don't insert the user message here — the chat API will do it
        self.conn.execute(
            "UPDATE conversations SET branch_reason = ?, branch_point_index = ? WHERE id = ?",
            (branch_reason, edit_message_index, new_id)
        )
        self.conn.commit()
        return new_id

    def get_branch_points(self, paper_id):
        """Return conversations that are branch points (have parent or children)."""
        rows = self.conn.execute(
            """SELECT c.*,
                (SELECT COUNT(*) FROM conversations WHERE parent_id = c.id) as children_count
               FROM conversations c
               WHERE c.paper_id = ?
                 AND (c.parent_id IS NOT NULL
                      OR EXISTS (SELECT 1 FROM conversations WHERE parent_id = c.id))
               ORDER BY c.created_at""",
            (paper_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_conversation_children(self, conv_id):
        """Get direct child conversations of a conversation."""
        rows = self.conn.execute(
            "SELECT * FROM conversations WHERE parent_id = ? ORDER BY created_at",
            (conv_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_conversation_title(self, conv_id, title):
        self.conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title, conv_id)
        )
        self.conn.commit()

    # ─── Messages ───

    def add_message(self, conversation_id, role, content, citations=None,
                    model=None, token_count=None, cost_usd=None, guard_result=""):
        cur = self.conn.execute(
            """INSERT INTO messages (conversation_id, role, content, citations,
                model, token_count, cost_usd, guard_result)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (conversation_id, role, content,
             json.dumps(citations) if citations else None,
             model, token_count, cost_usd, guard_result)
        )
        self.conn.execute(
            """UPDATE conversations
               SET message_count = (SELECT COUNT(*) FROM messages WHERE conversation_id = ?),
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (conversation_id, conversation_id)
        )
        self.conn.commit()
        return cur.lastrowid
        return cur.lastrowid

    def get_messages(self, conversation_id):
        rows = self.conn.execute(
            """SELECT * FROM messages WHERE conversation_id = ?
               ORDER BY created_at""",
            (conversation_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_message_feedback(self, message_id, feedback):
        self.conn.execute(
            "UPDATE messages SET feedback = ? WHERE id = ?",
            (feedback, message_id)
        )
        self.conn.commit()

    def get_message_count(self, conversation_id):
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = ?",
            (conversation_id,)
        ).fetchone()
        return row["cnt"] if row else 0

    def link_message_chunk(self, message_id, chunk_id):
        self.conn.execute(
            """INSERT OR IGNORE INTO message_chunks (message_id, chunk_id)
               VALUES (?, ?)""",
            (message_id, chunk_id)
        )
        self.conn.commit()

    def get_message_chunks(self, message_id):
        rows = self.conn.execute(
            """SELECT c.* FROM chunks c
               JOIN message_chunks mc ON c.id = mc.chunk_id
               WHERE mc.message_id = ?""",
            (message_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── Notes ───

    def add_note(self, paper_id, content, highlights=None, tags=None):
        cur = self.conn.execute(
            """INSERT INTO notes (paper_id, content, highlights, tags)
               VALUES (?, ?, ?, ?)""",
            (paper_id, content, json.dumps(highlights) if highlights else None, json.dumps(tags) if tags else None)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_notes_by_paper(self, paper_id):
        rows = self.conn.execute(
            "SELECT * FROM notes WHERE paper_id = ? ORDER BY updated_at DESC",
            (paper_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── Usage ───

    def log_usage(self, provider, model, task_type, input_tokens, output_tokens, cost_usd, conversation_id=None):
        self.conn.execute(
            """INSERT INTO llm_usage (provider, model, task_type,
                input_tokens, output_tokens, cost_usd, conversation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (provider, model, task_type, input_tokens, output_tokens, cost_usd, conversation_id)
        )
        self.conn.commit()

    def get_monthly_cost(self):
        row = self.conn.execute(
            """SELECT COALESCE(SUM(cost_usd), 0) as total
               FROM llm_usage
               WHERE strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now')"""
        ).fetchone()
        return row["total"] if row else 0.0

    def get_usage_by_conversation(self, conv_id):
        row = self.conn.execute(
            """SELECT COALESCE(SUM(cost_usd), 0) as total,
                      COALESCE(SUM(input_tokens), 0) as inp,
                      COALESCE(SUM(output_tokens), 0) as out
               FROM llm_usage WHERE conversation_id = ?""",
            (conv_id,)
        ).fetchone()
        return dict(row) if row else {"total": 0.0, "inp": 0, "out": 0}

    # ─── Hallucination feedback ───

    def add_hallucination_feedback(self, message_id, is_hallucination, description=""):
        self.conn.execute(
            """INSERT INTO hallucination_feedback (message_id, is_hallucination, description)
               VALUES (?, ?, ?)""",
            (message_id, is_hallucination, description)
        )
        self.conn.commit()

    # ─── Relations ───

    def add_relation(self, paper_a_id, paper_b_id, similarity):
        self.conn.execute(
            """INSERT OR REPLACE INTO relations (paper_a_id, paper_b_id, similarity)
               VALUES (?, ?, ?)""",
            (paper_a_id, paper_b_id, similarity)
        )
        self.conn.commit()

    def get_related_papers(self, paper_id):
        rows = self.conn.execute(
            """SELECT paper_b_id as related_id, similarity FROM relations WHERE paper_a_id = ?
               UNION
               SELECT paper_a_id as related_id, similarity FROM relations WHERE paper_b_id = ?""",
            (paper_id, paper_id)
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── Project-Paper association ───

    def add_paper_to_project(self, project_id, paper_id):
        self.conn.execute(
            "INSERT OR IGNORE INTO project_papers (project_id, paper_id) VALUES (?, ?)",
            (project_id, paper_id)
        )
        self.conn.commit()

    def remove_paper_from_project(self, project_id, paper_id):
        self.conn.execute(
            "DELETE FROM project_papers WHERE project_id = ? AND paper_id = ?",
            (project_id, paper_id)
        )
        self.conn.commit()

    def get_project_papers(self, project_id):
        rows = self.conn.execute(
            """SELECT p.* FROM papers p
               JOIN project_papers pp ON p.id = pp.paper_id
               WHERE pp.project_id = ?
               ORDER BY pp.added_at DESC""",
            (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.close()
