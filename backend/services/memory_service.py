"""User memory: cross-session preferences persisted as a single markdown file.
Loaded at conversation start (~300 tokens), updated via feedback linkage.

Design: one user.md file, no index, no multi-file topic organization.
Complexity rationale: single-user, single-project — full Memory 3-layer is over-engineering.
"""

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent  # paperbridge/
MEMORY_PATH = _ROOT / "storage" / "memory" / "user.md"


def load_user_memory() -> str:
    """Read the user memory file. Returns empty string if not found."""
    if MEMORY_PATH.exists():
        content = MEMORY_PATH.read_text(encoding="utf-8").strip()
        # Skip the YAML frontmatter when injecting into prompt
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return content
    return ""


def init_user_memory():
    """Create user.md from config.yaml profile if it doesn't exist."""
    if MEMORY_PATH.exists():
        return

    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    import yaml
    config_path = _ROOT / "config.yaml"
    profile = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
            profile = cfg.get("profile", {})

    field = profile.get("field", "")
    level = profile.get("level", "")
    language = profile.get("language", "Chinese")
    interests = profile.get("interests", [])

    lines = [
        "---",
        "type: user",
        "updated: auto-generated from config.yaml",
        "---",
        "",
    ]
    if field:
        lines.append(f"- 研究领域：{field}")
    if level:
        lines.append(f"- 专业水平：{level}")
    if language:
        lines.append(f"- 语言：{language}")
    if interests:
        lines.append(f"- 研究兴趣：{', '.join(interests)}")

    MEMORY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def update_memory_from_feedback(feedback_text: str):
    """Summarize user feedback into a rule and append to user.md."""
    if not feedback_text or not feedback_text.strip():
        return

    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not MEMORY_PATH.exists():
        init_user_memory()

    from core.llm_router import router

    prompt = (
        "总结以下用户反馈，提炼成一条可执行的规则（不超过30字，用中文）：\n"
        f"{feedback_text.strip()}"
    )
    try:
        summary = await router.complete_single(
            messages=[{"role": "user", "content": prompt}],
            provider="deepseek",
            task_type="compaction",
            max_tokens=60,
        )
    except Exception:
        return  # Silently skip if LLM unavailable

    summary = summary.strip()
    if not summary or len(summary) < 2:
        return  # Skip empty or nonsensical summaries

    entry = f"- {summary}"
    with open(MEMORY_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n{entry}\n")
