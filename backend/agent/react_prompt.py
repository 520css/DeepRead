"""ReAct system prompt builder (<500 tokens)."""

import yaml
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent  # paperbridge/
SKILLS_DIR = _ROOT / "skills"
_REFLECTIONS_DIR = _ROOT / "storage" / "agent_reflections"


def _discover_skills() -> list[dict]:
    """Scan skills/: single *.md files + directories with SKILL.md. Returns [{name, description, type, ...}]."""
    skills = []
    if not SKILLS_DIR.exists():
        return skills

    # Old format: skills/*.md (single file)
    for f in sorted(SKILLS_DIR.glob("*.md")):
        meta = _read_frontmatter(f)
        if meta:
            skills.append({
                "name": meta.get("name", f.stem),
                "description": meta.get("description", ""),
                "type": "simple",
            })

    # New format: skills/<name>/SKILL.md (directory bundle)
    for d in sorted(SKILLS_DIR.iterdir()):
        if d.is_dir() and (d / "SKILL.md").exists():
            meta = _read_frontmatter(d / "SKILL.md")
            if meta:
                skills.append({
                    "name": meta.get("name", d.name),
                    "description": meta.get("description", ""),
                    "type": "bundle",
                    "has_scripts": (d / "scripts").is_dir(),
                    "has_refs": (d / "references").is_dir(),
                })
    return skills


def _read_frontmatter(filepath: Path) -> dict | None:
    """Parse YAML frontmatter from a markdown file. Returns None on failure."""
    text = filepath.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                return yaml.safe_load(parts[1])
            except yaml.YAMLError:
                pass
    return None


def build_system_prompt(
    user_field: str = "", user_level: str = "", user_language: str = "Chinese",
    mode: str = "research", project_id: int = 0, paper_id: int = 0,
) -> str:
    """Build system prompt. mode: 'research' (paper reading) or 'agent' (general assistant)."""
    skills = _discover_skills()
    skills_section = ""
    if skills:
        lines = ["<skills>"]
        for s in skills:
            lines.append(f"- {s['name']}: {s['description']}")
        lines.append("</skills>")
        skills_section = "\n".join(lines)

    # Project context: list papers in this project
    project_section = ""
    if project_id:
        from data.db import PaperDB
        proj_db = PaperDB()
        try:
            papers = proj_db.get_project_papers(project_id)
            if papers:
                lines = ["<project_papers>"]
                for p in papers:
                    title = (p.get("title") or f"Paper #{p['id']}")[:80]
                    lines.append(f"- [{p['id']}] {title}")
                lines.append("</project_papers>")
                project_section = "\n".join(lines)
        finally:
            proj_db.close()

    # Single paper context: tell the agent which paper the user is viewing
    paper_section = ""
    if paper_id and not project_id:  # only for single-paper chat (project chat already lists papers)
        from data.db import PaperDB
        paper_db = PaperDB()
        try:
            paper = paper_db.get_paper(paper_id)
            if paper:
                title = paper.get("title") or f"Paper #{paper_id}"
                authors = paper.get("authors") or ""
                abstract = (paper.get("abstract") or "")[:500]
                lines = [f"<current_paper>"]
                lines.append(f"Paper ID: {paper_id} ← use read(paper_id={paper_id}, query=\"...\") to access this paper's full text")
                lines.append(f"Title: {title}")
                if authors:
                    lines.append(f"Authors: {authors}")
                if abstract:
                    lines.append(f"Abstract: {abstract}")
                lines.append("</current_paper>")
                paper_section = "\n".join(lines)
        finally:
            paper_db.close()

    persona = (
        "You are an AI assistant with full tool access. Use tools proactively — execute, don't just explain."
        if mode == "agent" else
        "You are a research assistant. Answer based on provided context."
    )

    rules = (
        """1. Use tools for everything — papers, code, charts, search
2. For papers: read/search/compare. For code: run(Python).
3. Files: use simple filenames. matplotlib/numpy/PIL available.
4. Cite: [P.X] for page when reading papers
5. Closing tags are EXACTLY </tool_call> and </tool_input> only. Never use </tool_card>, </tool_output>, </tool_action> or any other variation.
6. To use a skill: <tool_call>skill</tool_call><tool_input>{"name": "translate", "content": "text"}</tool_input>"""
        if mode == "agent" else
        """1. When asked about the current paper: call read(paper_id=X, query="your question") — query is REQUIRED. Do NOT search, do NOT rely on the abstract.
2. EVERY citation MUST include the first English words from the chunk you read. The chunk looks like [P.3] The core idea of FSRF... — you cite (P.3, \"The core idea of FSRF\") using straight quotes (\"). This is MANDATORY, not optional. Without the English snippet the reader cannot jump to the exact location.
3. Do not fabricate numbers, authors, or page numbers — every claim AND its page number must be directly from read results
4. Use tools proactively — read before answering, search before guessing
5. Closing tags are ONLY </tool_call> and </tool_input>. Never write </tool_card>, </tool_output>, </tool_action>, or any other variation. Double-check every closing tag.
6. To use a skill: <tool_call>skill</tool_call><tool_input>{"name": "translate", "content": "text"}</tool_input>"""
    )

    tools = """<tools>
- read(paper_id?, query, path?)   ← query is REQUIRED with paper_id!
- search(query, scope?)
- compare(paper_ids, dimension?)
- note(content, target?)
- skill(name, ...)
- run(code?, script?, args?)
</tools>"""

    fmt = """<format>
When calling a tool, output EXACTLY:
<tool_call>name</tool_call><tool_input>{"k":"v"}</tool_input>
When answering, output EXACTLY:
<answer>text here</answer>
The ONLY valid closing tags are </tool_call> and </tool_input>. Any other tag (</tool_card>, etc.) is WRONG.
</format>"""

    # Load recent agent reflections (tool-use learnings)
    reflections_section = _load_recent_reflections()

    return f"""{persona}

{tools}
{project_section}
{paper_section}
{skills_section}
{reflections_section}
{fmt}

<rules>
{rules}
</rules>"""


def _load_recent_reflections(max_items: int = 5, max_chars: int = 800) -> str:
    """Load agent reflections: digest (old summary) + recent files (latest lessons)."""
    if not _REFLECTIONS_DIR.exists():
        return ""
    lines = []

    # Layer 1: Digest (old reflections merged into one summary)
    digest_file = _REFLECTIONS_DIR / "_digest.md"
    if digest_file.exists():
        digest_text = digest_file.read_text(encoding="utf-8").strip()[:400]
        if digest_text:
            lines.append(digest_text)

    # Layer 2: Recent individual reflections
    files = sorted(
        [f for f in _REFLECTIONS_DIR.glob("*.md") if f.name != "_digest.md"],
        key=lambda f: f.stat().st_mtime
    )
    total = sum(len(l) for l in lines)
    recent_lines = []
    for f in reversed(files[-max_items:]):
        text = f.read_text(encoding="utf-8").strip()
        body = text.split("\n", 1)[-1].strip() if "\n" in text else text
        snippet = body[:150]
        if total + len(snippet) > max_chars:
            break
        recent_lines.append(f"- {snippet}")
        total += len(snippet)

    if not lines and not recent_lines:
        return ""
    result = "<recent_learnings>\n"
    if lines:
        result += "\n".join(lines)
    if recent_lines:
        if lines:
            result += "\n"
        result += "\n".join(recent_lines)
    result += "\n</recent_learnings>\n"
    return result


def build_user_message(question: str, user_field: str = "", user_level: str = "", user_language: str = "Chinese") -> str:
    """Build user message with profile prefix and user memory."""
    from services.memory_service import load_user_memory

    parts = []

    memory = load_user_memory()
    if memory:
        parts.append(f"[用户偏好]\n{memory[:2000]}\n")  # Truncate to ~500 tokens max

    if user_field or user_level:
        parts.append(f"Profile: {user_field} {user_level}".strip())
    parts.append(f"Answer in {user_language}.")
    parts.append(f"\n{question}")
    return "\n".join(parts)
