"""Dynamic context compaction (token-based, v2)."""

from typing import List, Dict
from core.llm_router import router

KEEP_LAST_MESSAGES = 8  # Keep last 4 rounds verbatim
TOKEN_THRESHOLD_RATIO = 0.8
TOKEN_LIMIT = 64000  # DeepSeek 64K context window


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 3)


def _total_tokens(messages: List[Dict]) -> int:
    return sum(_est_tokens(m["content"]) for m in messages if "content" in m)


async def compact(messages: List[Dict], conversation_id: int = None, cheap_provider: str = "deepseek") -> List[Dict]:
    """If total tokens > 80% limit, compress old messages into a user-message summary."""
    total = _total_tokens(messages)
    if total < TOKEN_LIMIT * TOKEN_THRESHOLD_RATIO:
        return messages

    split_idx = max(0, len(messages) - KEEP_LAST_MESSAGES)
    if split_idx <= 0:
        return messages

    # Keep system message (index 0) — never include in compaction
    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    old = messages[1:split_idx] if system_msg else messages[:split_idx]
    recent = messages[split_idx:]

    if not old:  # Only system message + recent messages, nothing to compact
        return messages

    prompt = _build_compaction_prompt(old)
    summary = await router.complete_single(
        messages=[{"role": "user", "content": prompt}],
        provider=cheap_provider, task_type="compaction", max_tokens=1024,
        conversation_id=conversation_id,
    )

    # Append as user message (does NOT override system prompt with tools)
    result = [system_msg] if system_msg else []
    result += recent
    result += [{
        "role": "user",
        "content": f"[历史对话摘要]\n{summary}\n\n以上是之前讨论的摘要。请基于此继续回答。",
    }]
    return result


def strip_meta(messages: List[Dict]) -> List[Dict]:
    """Strip _meta fields before sending to LLM (_ prefix = internal only)."""
    return [{k: v for k, v in m.items() if not k.startswith("_")}
            for m in messages]


def _build_compaction_prompt(messages: List[Dict]) -> str:
    lines = [f"{m.get('role', 'user')}: {m.get('content', '')[:300]}" for m in messages]
    return (
        "请用中文总结以下对话历史，保留关键事实、引用页码 [P.X]、核心问题与结论。300 字以内。\n\n"
        + "\n\n".join(lines)
    )
