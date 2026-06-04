"""ReAct agent loop v2: token compaction, Late Conversion, streaming fix.

Architecture:
1. Build messages: system_prompt + history + user_profile + question
2. Token-compact if > 80% limit → summary as user message (not system override)
3. Late Conversion: assistant messages carry _meta (turn, tool_calls, rag_chunks);
   strip_meta() filters _meta fields before every LLM call.
4. For each iteration (max 5):
   a. Non-streaming LLM call → parse <tool_call> or <answer>
   b. If tool: execute → observation → append (with _meta) → continue
   c. If answer: stream SSE content tokens
5. Save + guard check
"""

import json, re, asyncio
from pathlib import Path as _Path
from datetime import datetime as _dt
from typing import List, Dict, AsyncGenerator

from data.db import PaperDB
from core.llm_router import router
from core.guard import full_guard
from agent.context import compact, strip_meta
from agent.tool_registry import execute_tool, get_last_read_chunks
from agent.react_prompt import build_system_prompt, build_user_message

MAX_ITERATIONS = 10
_LOG_FILE = _Path(__file__).resolve().parent.parent.parent / "storage" / "agent_debug.log"  # paperbridge/storage/agent_debug.log
TOKEN_LIMIT = 64000  # DeepSeek 64K context window
_REFLECTIONS_DIR = _Path(__file__).resolve().parent.parent.parent / "storage" / "agent_reflections"
ERROR_KEYWORDS = ["ERROR", "No relevant", "failed", "not found", "Error:"]


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 3)


def _total_tokens(messages: List[dict]) -> int:
    return sum(_est_tokens(m.get("content", "")) for m in messages)


async def run_react_loop_streaming(
    paper_id: int,
    conv_id: int,
    question: str,
    provider: str = None,
    history: List[Dict] = None,
    user_field: str = "",
    user_level: str = "",
    user_language: str = "Chinese",
    cancel_event: asyncio.Event = None,
    system_prompt: str = None,
    project_id: int = 0,
) -> AsyncGenerator[dict, None]:
    """
    Streaming ReAct loop. Yields SSE-style events:
    {"event": "status", "data": "..."}
    {"event": "tool_call", "data": {"tool": "...", "params": {...}}}
    {"event": "observation", "data": "..."}
    {"event": "content", "data": {"token": "..."}}
    {"event": "done", "data": {"message_id": ..., "conv_id": ..., "guard": "...", "cancelled": bool}}
    """
    db = PaperDB()
    try:
        if not conv_id:
            conv_id = db.create_conversation(paper_id, title=question[:30])

        # ── Build messages ──
        sys_prompt = system_prompt or build_system_prompt(user_field, user_level, user_language, project_id=project_id, paper_id=paper_id)
        user_msg = build_user_message(question, user_field, user_level, user_language)
        messages = [{"role": "system", "content": sys_prompt}]

        # Load history
        if history:
            for h in history:
                if h.get("role") in ("user", "assistant"):
                    messages.append(h)
        else:
            db_msgs = db.get_messages(conv_id)
            for m in db_msgs[-30:]:
                if m["role"] in ("user", "assistant"):
                    messages.append({"role": m["role"], "content": m["content"]})

        messages.append({"role": "user", "content": user_msg})

        # Initial RAG context for the current paper
        paper = db.get_paper(paper_id)
        paper_title = paper.get("title", f"Paper #{paper_id}") if paper else f"Paper #{paper_id}"
        yield {"event": "status", "data": f"Reading: {paper_title[:60]}"}

        # ── Compaction ──
        if _total_tokens(messages) > TOKEN_LIMIT * 0.8:
            yield {"event": "status", "data": "Compacting context..."}
            messages = await compact(messages, conversation_id=conv_id)

        all_chunks = []
        tool_trace = []

        # ── Debug log: write session header ──
        _log_entry = {
            "ts": str(_dt.now()),
            "paper_id": paper_id,
            "conv_id": conv_id,
            "question": question,
            "system_prompt_len": len(sys_prompt),
        }
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as _f:
            _f.write(json.dumps(_log_entry, ensure_ascii=False) + "\n")

        for iteration in range(MAX_ITERATIONS):
            # Steering: check for cancellation before each iteration
            if cancel_event and cancel_event.is_set():
                yield {"event": "done", "data": {"conv_id": conv_id, "cancelled": True, "text": "已停止生成。"}}
                return

            yield {"event": "status", "data": f"Thinking... ({iteration + 1}/{MAX_ITERATIONS})"}

            # Non-streaming call for tool decision phase
            response = ""
            async for token in router.complete(
                strip_meta(messages), provider=provider, task_type="qa",
                conversation_id=conv_id, max_tokens=8192, max_retries=2,
            ):
                response += token

            # Parse tool calls
            tool_calls = _parse_tool_calls(response)

            if tool_calls:
                turn_rag_chunks = []
                for tool_name, tool_params in tool_calls:
                    if "paper_id" not in tool_params or tool_params["paper_id"] is None:
                        tool_params["paper_id"] = paper_id

                    yield {"event": "tool_call", "data": {"tool": tool_name, "params": tool_params}}

                    observation = await execute_tool(tool_name, tool_params, paper_id=paper_id, project_id=project_id)
                    yield {"event": "observation", "data": observation[:8000]}

                    tool_trace.append({
                        "iteration": iteration + 1, "tool": tool_name,
                        "params": tool_params, "observation": observation[:8000],
                        "is_error": any(kw in observation for kw in ERROR_KEYWORDS),
                    })

                    # Track RAG chunks for guard (from tool_registry, no re-retrieval)
                    read_chunks = get_last_read_chunks() if tool_name == "read" else []
                    if read_chunks:
                        all_chunks.extend(read_chunks)
                        turn_rag_chunks.extend(read_chunks)

                # Debug log: full tool call + observation
                with open(_LOG_FILE, "a", encoding="utf-8") as _f:
                    _log = {
                        "iter": iteration + 1,
                        "tools": [{"name": n, "params": p} for n, p in tool_calls],
                        "observation": observation[:8000],
                    }
                    if read_chunks:
                        _log["read_chunks"] = [{"page": c["page_number"], "text": c["content"]} for c in read_chunks]
                    _f.write(json.dumps(_log, ensure_ascii=False) + "\n")

                # Append assistant message with _meta (Late Conversion)
                messages.append({
                    "role": "assistant",
                    "content": response,
                    "_meta": {
                        "turn": iteration + 1,
                        "tool_calls": [{"name": name, "params": params} for name, params in tool_calls],
                        "rag_chunks": [{"page": c.get("page_number")} for c in turn_rag_chunks],
                    },
                })
                obs_text = "\n\n".join(
                    f"<observation from='{t['tool']}'>\n{t['observation']}\n</observation>"
                    for t in tool_trace[-len(tool_calls):]
                )
                messages.append({"role": "user", "content": obs_text})
                continue

            # No tool call → this is the final answer
            final_answer = _extract_answer(response) or response

            # Stream answer in word-sized chunks for smooth rendering
            words = final_answer.split(" ")
            for i, w in enumerate(words):
                token = w + (" " if i < len(words) - 1 else "")
                yield {"event": "content", "data": {"token": token}}

            # Guard
            guard_result = full_guard(paper_id, final_answer, all_chunks)

            # Debug log: guard + answer
            with open(_LOG_FILE, "a", encoding="utf-8") as _f:
                _f.write(json.dumps({
                    "final": True,
                    "guard": guard_result or "(clean)",
                    "chunks_used": len(all_chunks),
                    "answer_preview": final_answer,
                }, ensure_ascii=False) + "\n" + "=" * 60 + "\n")

            # Reflection: analyze tool_trace for improvement patterns
            try:
                errors = [t for t in tool_trace if t.get("is_error")]
                success = [t for t in tool_trace if not t.get("is_error")]
                if tool_trace:  # only reflect if tools were actually used
                    reflection_prompt = _build_reflection_prompt(errors, success, sys_prompt, messages, tool_trace)
                    reflection = await router.complete_single(
                        messages=[{"role": "user", "content": reflection_prompt}],
                        provider="deepseek", task_type="compaction", max_tokens=512,
                    )
                    _save_reflection(conv_id, reflection, len(errors), len(success))
            except Exception:
                pass  # reflection failure must not break main flow

            # Save
            db.add_message(conv_id, "user", question)
            msg_id = db.add_message(conv_id, "assistant", final_answer,
                           citations=json.dumps([{"page": c.get("page_number")} for c in all_chunks]),
                           model=provider, token_count=len(final_answer) // 4,
                           guard_result=guard_result)

            print(f"[loop] done guard_result={repr(guard_result)}")
            yield {"event": "done", "data": {
                "message_id": msg_id, "conv_id": conv_id,
                "tool_trace": tool_trace, "guard_result": guard_result,
                "text": final_answer,
            }}
            return

        # Max iterations exceeded
        final = "After multiple search attempts, I could not find enough information. Please try rephrasing."
        yield {"event": "done", "data": {"message_id": None, "conv_id": conv_id, "text": final}}
    finally:
        db.close()


# ── Helpers ──

def _parse_tool_calls(text: str) -> list:
    """Parse <tool_call>/<tool_input> pairs independently, then zip by position."""
    text = re.sub(r"```(?:xml|html)?\s*", "", text)
    text = re.sub(r"```", "", text)

    tc_pat = re.compile(r"<tool_call>\s*(.+?)\s*</tool_call>", re.DOTALL)
    ti_pat = re.compile(r"<tool_input>\s*(.+?)\s*</tool_input>", re.DOTALL)

    names = tc_pat.findall(text)
    inputs = ti_pat.findall(text)

    results = []
    for name, raw_input in zip(names, inputs):
        try:
            params = json.loads(raw_input.strip())
        except json.JSONDecodeError:
            params = {}
        results.append((name.strip(), params))
    return results


def _extract_answer(text: str) -> str | None:
    """Extract <answer>...</answer> content."""
    m = re.search(r"<answer>\s*(.+?)\s*</answer>", text, re.DOTALL)
    return m.group(1).strip() if m else None


def _build_reflection_prompt(errors: list, success: list, system_prompt: str, messages: list, tool_trace: list) -> str:
    """Build a reflection prompt with full Agent context: system prompt + conversation + tool calls."""
    # Agent conversation (strip _meta fields)
    agent_msgs = []
    for m in strip_meta(messages):
        role = m.get("role", "?")
        content = m.get("content", "")[:300]
        agent_msgs.append(f"[{role}] {content}")

    parts = [
        "你是 Agent 反思模块。以下是 Agent 完成任务时的完整上下文。分析工具选择是否最优，输出改进建议（200 字以内）。",
        f"\n## 系统提示词（节选）\n{system_prompt[:1500]}",
        f"\n## 对话\n" + "\n".join(agent_msgs[-8:]),
    ]
    if errors:
        parts.append(f"\n## 失败的调用 ({len(errors)})")
        for e in errors:
            parts.append(f"  [{e['iteration']}] {e['tool']}: {e['observation'][:150]}")
    if success:
        parts.append(f"\n## 成功的调用 ({len(success)})")
        for s in success:
            parts.append(f"  [{s['iteration']}] {s['tool']}: {s['observation'][:100]}")

    return "\n".join(parts)


def _save_reflection(conv_id: int, text: str, error_count: int, success_count: int):
    """Persist reflection to disk with tiered convergence:
    - < 10 files: keep all
    - 10-20 files: merge oldest 10 into _digest.md, delete them
    - > 20 files: merge all but recent 5 into _digest.md, delete them
    """
    _REFLECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.now().strftime("%Y%m%d-%H%M%S")
    content = text.strip()[:200]
    if not content:
        return
    header = f"conv={conv_id} errors={error_count} success={success_count}\n"
    (_REFLECTIONS_DIR / f"{ts}.md").write_text(header + content, encoding="utf-8")

    # Tiered convergence
    all_files = sorted(
        [f for f in _REFLECTIONS_DIR.glob("*.md") if f.name != "_digest.md"],
        key=lambda f: f.stat().st_mtime
    )
    n = len(all_files)
    if n >= 10 and n <= 20:
        # Merge oldest 10
        _merge_reflections(all_files[:10])
        for f in all_files[:10]:
            try: f.unlink()
            except Exception: pass
    elif n > 20:
        # Merge all but recent 5
        old = all_files[:-5]
        _merge_reflections(old)
        for f in old:
            try: f.unlink()
            except Exception: pass


async def _merge_reflections(files: list):
    """Summarize old reflections into _digest.md via DeepSeek compaction."""
    texts = []
    for f in files:
        try:
            t = f.read_text(encoding="utf-8").strip()
            body = t.split("\n", 1)[-1].strip() if "\n" in t else t
            if body:
                texts.append(body[:150])
        except Exception:
            pass
    if not texts:
        return

    # Merge with existing digest if present
    digest_file = _REFLECTIONS_DIR / "_digest.md"
    existing = ""
    if digest_file.exists():
        existing = digest_file.read_text(encoding="utf-8").strip()[:300]

    prompt = "请将以下 Agent 反思记录提炼为一条简洁的经验摘要（300字以内），保留关键错误模式和改进建议：\n\n"
    if existing:
        prompt += f"已有摘要:\n{existing}\n\n"
    prompt += "\n".join(f"- {t}" for t in texts)

    try:
        summary = await router.complete_single(
            messages=[{"role": "user", "content": prompt}],
            provider="deepseek", task_type="compaction", max_tokens=512,
        )
        digest_file.write_text(summary.strip()[:500], encoding="utf-8")
    except Exception:
        pass  # merge failure is non-critical
