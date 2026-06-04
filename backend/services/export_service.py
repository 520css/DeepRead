"""Export service: convert notes and conversations to Markdown for Obsidian sync."""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from data.db import PaperDB

_ROOT = Path(__file__).resolve().parent.parent.parent  # paperbridge/
EXPORT_DIR = _ROOT / "storage" / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


class ExportService:
    """Export notes and conversations as Markdown files."""

    def __init__(self):
        self.db = PaperDB()

    # ─── Note Export ───

    def export_note(self, note_id: int) -> Optional[Path]:
        """Export a single note as Markdown with YAML frontmatter."""
        note = self.db.conn.execute(
            "SELECT * FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if not note:
            return None

        note = dict(note)
        paper_id = note.get("paper_id")
        paper = self.db.get_paper(paper_id) if paper_id else None

        # Build frontmatter
        frontmatter = {
            "title": f"Note #{note['id']}",
            "paper_id": paper_id,
            "paper_title": paper.get("title", "") if paper else "",
            "date": str(note.get("created_at", ""))[:10],
        }
        try:
            frontmatter["tags"] = json.loads(note.get("tags", "[]"))
        except (json.JSONDecodeError, TypeError):
            frontmatter["tags"] = []

        content = self._build_markdown(frontmatter, note.get("content", ""))

        # Write file
        filename = f"note_{note['id']}_{frontmatter['date']}.md"
        filepath = EXPORT_DIR / filename
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def export_all_notes(self, paper_id: Optional[int] = None) -> Path:
        """Export all notes (optionally filtered by paper) as a single Markdown file."""
        if paper_id:
            notes = self.db.get_notes_by_paper(paper_id)
        else:
            rows = self.db.conn.execute(
                "SELECT * FROM notes ORDER BY created_at DESC"
            ).fetchall()
            notes = [dict(r) for r in rows]

        lines = ["# PaperBridge Notes Export\n", f"Exported: {datetime.now().isoformat()}\n\n---\n"]

        for note in notes:
            paper_id_n = note.get("paper_id")
            paper = self.db.get_paper(paper_id_n) if paper_id_n else None
            paper_title = paper.get("title", "General") if paper else "General"

            lines.append(f"## Note #{note['id']} — {paper_title}\n")
            lines.append(f"*Created: {note.get('created_at', '')}*\n")
            lines.append(note.get("content", ""))
            lines.append("\n---\n")

        filename = f"notes_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        filepath = EXPORT_DIR / filename
        filepath.write_text("\n".join(lines), encoding="utf-8")
        return filepath

    # ─── Conversation Export ───

    def export_conversation(self, conv_id: int) -> Optional[Path]:
        """Export a conversation as Markdown."""
        conv = self.db.get_conversation(conv_id)
        if not conv:
            return None

        conv = dict(conv)
        messages = self.db.get_messages(conv_id)

        paper_id = conv.get("paper_id")
        paper = self.db.get_paper(paper_id) if paper_id else None
        paper_title = paper.get("title", f"Paper #{paper_id}") if paper else "General"

        lines = [
            f"# {conv.get('title', 'Conversation')}",
            f"",
            f"**Paper**: {paper_title}",
            f"**Model**: {conv.get('model', 'unknown')}",
            f"**Created**: {conv.get('created_at', '')}",
            f"**Messages**: {len(messages)}",
            f"",
            "---",
            "",
        ]

        for m in messages:
            role_emoji = "🧑" if m["role"] == "user" else "🤖"
            lines.append(f"### {role_emoji} {m['role'].capitalize()}")
            lines.append("")
            lines.append(m.get("content", ""))
            lines.append("")

            citations = m.get("citations")
            if citations:
                try:
                    cites = json.loads(citations)
                    if cites:
                        lines.append("*References:*")
                        for c in cites:
                            if isinstance(c, dict):
                                lines.append(f"- P.{c.get('page', '?')}")
                            elif isinstance(c, str):
                                lines.append(f"- {c}")
                        lines.append("")
                except (json.JSONDecodeError, TypeError):
                    pass

            lines.append("---\n")

        filename = f"conversation_{conv_id}_{conv.get('created_at','')[:10]}.md"
        filepath = EXPORT_DIR / filename
        filepath.write_text("\n".join(lines), encoding="utf-8")
        return filepath

    # ─── Highlight + Note Compilation ───

    def compile_paper_notes(self, paper_id: int) -> Optional[Path]:
        """Compile all highlights + notes for a paper into a single Markdown."""
        paper = self.db.get_paper(paper_id)
        if not paper:
            return None

        highlights = self.db.get_highlights_by_paper(paper_id)
        notes = self.db.get_notes_by_paper(paper_id)

        lines = [
            f"# {paper.get('title', f'Paper #{paper_id}')}",
            f"",
            f"**Authors**: {paper.get('authors', 'Unknown')}",
            f"**Year**: {paper.get('year', 'N/A')}",
            f"**DOI**: {paper.get('doi', 'N/A')}",
            f"",
            "---",
            "",
            f"## Highlights ({len(highlights)})",
            "",
        ]

        for h in highlights:
            lines.append(f"> {h.get('snippet', '')}")
            lines.append(f"*P.{h.get('page_number', '?')}*")
            if h.get("note"):
                lines.append(f"\n{h['note']}")
            lines.append("")

        if notes:
            lines.append(f"## Notes ({len(notes)})")
            lines.append("")
            for n in notes:
                lines.append(f"### Note #{n['id']}")
                lines.append(f"*{n.get('created_at', '')}*")
                lines.append("")
                lines.append(n.get("content", ""))
                lines.append("")

        filename = f"paper_{paper_id}_compilation.md"
        filepath = EXPORT_DIR / filename
        filepath.write_text("\n".join(lines), encoding="utf-8")
        return filepath

    def close(self):
        self.db.close()

    # ─── Helpers ───

    def _build_markdown(self, frontmatter: dict, content: str) -> str:
        parts = ["---"]
        for k, v in frontmatter.items():
            if isinstance(v, list):
                parts.append(f"{k}: [{', '.join(v)}]")
            else:
                parts.append(f"{k}: {v}")
        parts.append("---\n")
        parts.append(content)
        return "\n".join(parts)
