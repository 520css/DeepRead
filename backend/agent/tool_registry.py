"""ReAct tool registry: 6 core tools + progressive skill loading."""

import json
from pathlib import Path
from typing import Dict, Any

_ROOT = Path(__file__).resolve().parent.parent.parent  # paperbridge/
SKILLS_DIR = _ROOT / "skills"

# ─── Tool definitions ───

TOOL_DEFINITIONS: Dict[str, dict] = {
    "read": {
        "description": "Read paper content via RAG semantic search (query is REQUIRED when using paper_id), or read any local file by path.",
        "parameters": {
            "paper_id": {"type": "int", "required": False, "description": "Paper ID to search in. You MUST also provide query."},
            "query": {"type": "str", "required": False, "description": "What to search for (REQUIRED for paper RAG retrieval)"},
            "path": {"type": "str", "required": False, "description": "Read any local file (notes, logs, etc.). No paper_id/query needed."},
        },
    },
    "search": {
        "description": "Search for papers — ChromaDB semantic search (scope=local) or academic APIs (scope=academic).",
        "parameters": {
            "query": {"type": "str", "required": True, "description": "Search query"},
            "scope": {"type": "str", "required": False, "default": "local", "description": "'local' for ChromaDB or 'academic' for arXiv+Semantic Scholar"},
        },
    },
    "compare": {
        "description": "Compare 2-5 papers on a dimension (method, results, etc.). Runs in parallel for speed.",
        "parameters": {
            "paper_ids": {"type": "list[int]", "required": True, "description": "Paper IDs to compare"},
            "dimension": {"type": "str", "required": False, "default": "method", "description": "Dimension: method, results, contribution, architecture"},
        },
    },
    "note": {
        "description": "Save Markdown notes, todos, comparisons, or research logs to local files.",
        "parameters": {
            "content": {"type": "str", "required": True, "description": "Markdown content to save"},
            "target": {"type": "str", "required": False, "default": "notes", "description": "'notes', 'todo', 'comparisons', or 'log'"},
            "tags": {"type": "list[str]", "required": False, "description": "Tags for organization"},
        },
    },
    "skill": {
        "description": "Load a skill prompt template to guide complex multi-step tasks.",
        "parameters": {
            "name": {"type": "str", "required": True, "description": "Skill name (matches skills/*.md frontmatter)"},
            "paper_id": {"type": "int", "required": False, "description": "Associated paper ID for variable substitution"},
        },
    },
    "run": {
        "description": "Execute Python code or a Python script. For charts, web requests, data analysis, etc.",
        "parameters": {
            "code": {"type": "str", "required": False, "description": "Python code to execute"},
            "script": {"type": "str", "required": False, "description": "Path to an existing Python script"},
            "args": {"type": "list[str]", "required": False, "description": "CLI arguments for the script"},
        },
    },
}


# ─── Tool executor ───

# Module-level storage for chunks retrieved by read tool (consumed by loop.py for guard)
_last_read_chunks: list = []

def get_last_read_chunks() -> list:
    """Return and clear the chunks from the last read tool call."""
    global _last_read_chunks
    chunks = _last_read_chunks
    _last_read_chunks = []
    return chunks


async def execute_tool(name: str, params: dict, paper_id: int = None, project_id: int = 0) -> str:
    """Dispatch tool call and return observation string."""

    if name == "read":
        from tools.read import read
        from core.rag import retrieve
        pid = params.get("paper_id", paper_id)
        query = params.get("query", "")
        path = params.get("path", "")

        if path:
            # Read arbitrary file
            fp = Path(path)
            if not fp.is_absolute():
                fp = _ROOT / path
            if not fp.exists():
                return f"[read] File not found: {path}"
            text = fp.read_text(encoding="utf-8")[:5000]
            return f"[read] {path}\n{text}"

        if pid:
            if not query:
                return "[read] ERROR: query is REQUIRED when using paper_id. You MUST provide query=\"what you want to know\"."
            # Retrieve chunks here so we can also pass them to guard
            global _last_read_chunks
            _last_read_chunks = retrieve(pid, query, top_k=15)
            if not _last_read_chunks:
                return "[read] No relevant passages found for this query."
            parts = [f"[P.{ch['page_number']}] {ch['content']}" for ch in _last_read_chunks]
            return f"[read result]\n" + "\n\n".join(parts)

        return "[read] Provide paper_id (with query) or path."

    elif name == "search":
        query = params.get("query", "")
        scope = params.get("scope", "local")

        if scope == "academic":
            from services.recommend_service import _fetch_arxiv
            try:
                results = await _fetch_arxiv(query, max_results=10, sort_by="relevance")
                if not results:
                    return "[search] No academic results found."
                lines = [f"[search] Found {len(results)} papers from arXiv (relevance sorted):"]
                for i, p in enumerate(results):
                    lines.append(f"  {i+1}. {p.get('title','?')} ({p.get('authors','')[:60]}, {p.get('published','')[:10]})")
                return "\n".join(lines)
            except Exception as e:
                return f"[search] Academic search failed: {e}"

        # scope == project: search only within project papers
        if scope == "project" and project_id:
            from data.db import PaperDB
            proj_db = PaperDB()
            try:
                project_papers = proj_db.get_project_papers(project_id)
                paper_ids = [p["id"] for p in project_papers]
            finally:
                proj_db.close()
            from tools.search import search as local_search
            results = local_search(query, scope="global", paper_ids=paper_ids) if paper_ids else []
        else:
            # scope == local: ChromaDB semantic search
            from tools.search import search as local_search
            results = local_search(query, scope="global")
        if not results:
            return "[search] No local papers found."
        lines = [f"[search] Found {len(results)} papers:"]
        for i, p in enumerate(results[:10]):
            lines.append(f"  {i+1}. [{p.get('id')}] {p.get('title','?')} ({p.get('year','?')})")
        return "\n".join(lines)

    elif name == "compare":
        from tools.compare import compare
        ids = params.get("paper_ids", [])
        dimension = params.get("dimension", "method")
        result = await compare(ids, dimension=dimension)
        if not result or result.startswith("[Error"):
            return f"[compare] Could not compare papers {ids}."
        return f"[compare result]\n{result}"

    elif name == "note":
        from tools.note import save
        content = params.get("content", "")
        target = params.get("target", "notes")
        tags = params.get("tags")
        result = save(content, target=target, tags=tags)
        return f"[note] {result}"

    elif name == "skill":
        skill_name = params.get("name", "")
        prompt = ""
        extras = []

        # New format: skills/<name>/SKILL.md (directory bundle)
        dir_path = SKILLS_DIR / skill_name
        if dir_path.is_dir() and (dir_path / "SKILL.md").exists():
            prompt = (dir_path / "SKILL.md").read_text(encoding="utf-8")
            if (dir_path / "scripts").is_dir():
                scripts = sorted((dir_path / "scripts").iterdir())
                extras.append("Scripts: " + ", ".join(
                    f"run(script='skills/{skill_name}/scripts/{s.name}')" for s in scripts if s.suffix == ".py"
                ))
            if (dir_path / "references").is_dir():
                refs = sorted((dir_path / "references").iterdir())
                extras.append("References: " + ", ".join(
                    f"read(path='skills/{skill_name}/references/{r.name}')" for r in refs if r.suffix == ".md"
                ))
        else:
            # Old format: skills/<name>.md
            sp = SKILLS_DIR / f"{skill_name}.md"
            if not sp.exists():
                return f"[skill] Skill '{skill_name}' not found. Available: {_list_skill_names()}"
            prompt = sp.read_text(encoding="utf-8")

        # Substitute variables
        if params.get("paper_id"):
            prompt = prompt.replace("{paper_id}", str(params["paper_id"]))
        for k, v in params.items():
            prompt = prompt.replace(f"{{{k}}}", str(v))

        result = f"[skill] {skill_name} loaded:\n{prompt[:4000]}"
        if extras:
            result += "\n\n" + "\n".join(extras)
        return result

    elif name == "run":
        from tools.run import execute as run_exec
        code = params.get("code", "")
        script = params.get("script", "")
        args = params.get("args") or []
        if script:
            sp = Path(script)
            if not sp.is_absolute():
                sp = _ROOT / script
            # Security: scripts must be under skills/ directory
            if "skills" not in sp.parts:
                return f"[run] Security: script must be under skills/ directory. Got: {script}"
            if not sp.exists():
                return f"[run] Script not found: {script}"
            code = sp.read_text(encoding="utf-8")
            # Prepend args as sys.argv for scripts
            if args:
                arg_setup = f"import sys; sys.argv = ['{script}'] + {json.dumps(args)}\n"
                code = arg_setup + code
        if not code:
            return "[run] Provide code or script."
        return run_exec(code)

    else:
        return f"[Error] Unknown tool: {name}"


def _list_skill_names() -> str:
    if not SKILLS_DIR.exists():
        return "none"
    names = set()
    for f in sorted(SKILLS_DIR.glob("*.md")):
        names.add(f.stem)
    for d in sorted(SKILLS_DIR.iterdir()):
        if d.is_dir() and (d / "SKILL.md").exists():
            names.add(d.name)
    return ", ".join(sorted(names))


def format_tools_for_prompt() -> str:
    """Generate <tools> section for system prompt."""
    lines = []
    for name, defn in TOOL_DEFINITIONS.items():
        params_desc = []
        for pname, pinfo in defn["parameters"].items():
            req = "(required)" if pinfo.get("required") else "(optional)"
            params_desc.append(f"      {pname} ({pinfo['type']}) {req}: {pinfo['description']}")
        lines.append(f"  - {name}: {defn['description']}")
        lines.extend(params_desc)
    return "\n".join(lines)
