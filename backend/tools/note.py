"""Tool: save notes/highlights/todos/comparisons/log to Markdown files."""

from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).resolve().parent.parent.parent  # paperbridge/

FOLDERS = {
    "notes": _ROOT / "storage" / "notes",
    "todo": _ROOT / "storage" / "todo",
    "comparisons": _ROOT / "storage" / "comparisons",
    "log": _ROOT / "storage" / "log",
}

for folder in FOLDERS.values():
    folder.mkdir(parents=True, exist_ok=True)


def save(content: str, target: str = "notes", paper_id: int = None, page: int = None, tags: list = None) -> str:
    """Save content to file-based workflow.
    target: notes | todo | comparisons | log
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%Y%m%d_%H%M%S")

    if target == "todo":
        filepath = FOLDERS["todo"] / f"readme.md"
        line = f"- [ ] {content}"
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return f"[Todo saved to {filepath}]"

    if target == "comparisons":
        filepath = FOLDERS["comparisons"] / f"comparison_{time_str}.md"
        header = f"# 论文对比\n\n生成时间: {date_str}\n\n"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(header + content)
        return f"[Comparison saved to {filepath}]"

    if target == "log":
        filepath = FOLDERS["log"] / f"research_log.md"
        line = f"\n## {date_str}\n\n{content}\n"
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(line)
        return f"[Log appended to {filepath}]"

    # default: notes
    folder = FOLDERS["notes"]
    fname = f"note_p{paper_id or 'general'}_{time_str}.md"
    filepath = folder / fname
    meta = []
    if paper_id:
        meta.append(f"paper_id: {paper_id}")
    if page:
        meta.append(f"page: {page}")
    if tags:
        meta.append(f"tags: {', '.join(tags)}")
    header = "---\n" + "\n".join(meta) + "\n---\n\n" if meta else ""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(header + content)
    return f"[Note saved to {filepath}]"
