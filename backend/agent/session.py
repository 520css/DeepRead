"""Tree-shaped session management."""

from typing import List, Dict, Optional
from data.db import PaperDB


class SessionManager:
    """Manages conversation trees for a paper."""

    def __init__(self, paper_id: int):
        self.paper_id = paper_id
        self.db = PaperDB()

    def list_sessions(self) -> List[Dict]:
        return self.db.list_conversations(self.paper_id)

    def create_session(self, title: str, parent_id: int = None, model: str = None) -> int:
        return self.db.create_conversation(self.paper_id, title, parent_id=parent_id, model=model)

    def branch_session(self, from_conv_id: int, branch_reason: str = "用户分支") -> int:
        return self.db.branch_conversation(from_conv_id, branch_reason=branch_reason)

    def get_messages(self, conv_id: int) -> List[Dict]:
        return self.db.get_messages(conv_id)

    def close(self):
        self.db.close()


def build_tree_display(paper_id: int, current_conv_id: int = None) -> str:
    """Build a simple text tree for Gradio Markdown display."""
    db = PaperDB()
    try:
        convs = db.get_conversation_tree(paper_id)
        if not convs:
            return "暂无会话"

        # Build parent -> children map
        children = {}
        for c in convs:
            pid = c.get("parent_id")
            if pid not in children:
                children[pid] = []
            children[pid].append(c)

        lines = []

        def _render(node_id, depth=0):
            for c in children.get(node_id, []):
                prefix = "  " * depth
                marker = "▸" if c["id"] == current_conv_id else "  "
                title = c.get("title") or f"对话 #{c['id']}"
                lines.append(f"{prefix}{marker} {title}")
                _render(c["id"], depth + 1)

        _render(None)
        return "\n".join(lines)
    finally:
        db.close()
