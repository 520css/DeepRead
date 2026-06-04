"""Chat service: wraps ReAct loop for SSE streaming to frontend."""

import json, asyncio
from typing import AsyncGenerator, Dict, Optional
from dataclasses import dataclass

from agent.loop import run_react_loop_streaming

END_OF_STREAM = "END_OF_STREAM"


@dataclass
class ChatRequest:
    paper_id: int
    conversation_id: int = 0
    question: str = ""
    provider: str | None = None
    model: str | None = None
    history: list | None = None
    user_field: str = ""
    user_level: str = ""
    user_language: str = "Chinese"


class ChatService:
    _active_cancels: dict = {}  # class-level: conv_id → asyncio.Event

    def __init__(self, user_field="", user_level="", user_language="Chinese"):
        self.user_field = user_field
        self.user_level = user_level
        self.user_language = user_language

    async def chat_stream(self, request: ChatRequest) -> AsyncGenerator[bytes, None]:
        """
        Stream ReAct loop events to frontend.
        Format: JSON chunk + END_OF_STREAM delimiter.
        """
        cancel = asyncio.Event()
        ChatService._active_cancels[request.conversation_id] = cancel
        try:
            async for event in run_react_loop_streaming(
                paper_id=request.paper_id,
                conv_id=request.conversation_id,
                question=request.question,
                provider=request.provider,
                user_field=request.user_field or self.user_field,
                user_level=request.user_level or self.user_level,
                user_language=request.user_language or self.user_language,
                cancel_event=cancel,
            ):
                etype = event.get("event", "")
                data = event.get("data", "")

                if etype == "content":
                    token = data if isinstance(data, str) else data.get("token", "")
                    if token:
                        yield _chunk("content", token)

                elif etype == "tool_call":
                    yield _chunk("content", f"\n\n🔧 *{data.get('tool', '?')}...*\n\n")

                elif etype == "observation":
                    pass  # Don't show raw observations to user

                elif etype == "done":
                    done_data = data if isinstance(data, dict) else {}
                    print(f"[chat_service] done guard_result={repr(done_data.get('guard_result', 'MISSING'))}")
                    cancelled = done_data.get("cancelled", False)
                    if cancelled:
                        yield _chunk("content", "\n\n⏹ *已停止生成*\n\n")
                    refs = done_data.get("tool_trace", [])
                    references = [{"page": t.get("params", {}).get("page", "?")} for t in refs if t.get("tool") == "read"]
                    if not references:
                        references = [{"text": "See response for citations"}]
                    yield _chunk("references", references)
                    yield _chunk("done", {"conv_id": done_data.get("conv_id"), "cancelled": cancelled, "message_id": done_data.get("message_id"), "guard_result": done_data.get("guard_result", "")})
                    return

            yield _chunk("done", {})
        finally:
            ChatService._active_cancels.pop(request.conversation_id, None)

    async def project_chat_stream(self, project_id: int, question: str) -> AsyncGenerator[bytes, None]:
        """Streaming chat scoped to a project's papers."""
        from agent.react_prompt import build_system_prompt

        async for event in run_react_loop_streaming(
            paper_id=0, conv_id=0, question=question,
            provider="deepseek", project_id=project_id,
            system_prompt=build_system_prompt(mode="research", project_id=project_id),
        ):
            etype = event.get("event", "")
            data = event.get("data", "")

            if etype == "status":
                yield _chunk("status", data)
            elif etype == "tool_call":
                tool = data.get("tool", "?") if isinstance(data, dict) else str(data)
                params = data.get("params", {}) if isinstance(data, dict) else {}
                yield _chunk("tool_call", {"tool": tool, "params": params})
            elif etype == "observation":
                yield _chunk("observation", data if isinstance(data, str) else str(data)[:2000])
            elif etype == "content":
                token = data if isinstance(data, str) else data.get("token", "")
                if token:
                    yield _chunk("content", token)
            elif etype == "done":
                d = data if isinstance(data, dict) else {}
                yield _chunk("done", {"conv_id": d.get("conv_id"), "tool_trace": d.get("tool_trace", []), "message_id": d.get("message_id"), "guard_result": d.get("guard_result", "")})
                return
        yield _chunk("done", {})

    async def project_conversation_stream(self, project_id: int, conv_id: int, question: str) -> AsyncGenerator[bytes, None]:
        """Streaming chat in a project conversation (full SSE events)."""
        from agent.react_prompt import build_system_prompt

        async for event in run_react_loop_streaming(
            paper_id=0, conv_id=conv_id, question=question,
            provider="deepseek", project_id=project_id,
            system_prompt=build_system_prompt(mode="research", project_id=project_id),
        ):
            etype = event.get("event", "")
            data = event.get("data", "")
            if etype == "status":
                yield _chunk("status", data)
            elif etype == "tool_call":
                tool = data.get("tool", "?") if isinstance(data, dict) else str(data)
                params = data.get("params", {}) if isinstance(data, dict) else {}
                yield _chunk("tool_call", {"tool": tool, "params": params})
            elif etype == "observation":
                yield _chunk("observation", data if isinstance(data, str) else str(data)[:2000])
            elif etype == "content":
                token = data if isinstance(data, str) else data.get("token", "")
                if token:
                    yield _chunk("content", token)
            elif etype == "done":
                d = data if isinstance(data, dict) else {}
                yield _chunk("done", {"conv_id": d.get("conv_id"), "tool_trace": d.get("tool_trace", []), "message_id": d.get("message_id"), "guard_result": d.get("guard_result", "")})
                return
        yield _chunk("done", {})

    async def agent_chat_stream(self, req) -> AsyncGenerator[bytes, None]:
        """Streaming agent chat with general-purpose system prompt (no paper binding)."""
        from agent.react_prompt import build_system_prompt

        conv_id = getattr(req, "conversation_id", 0) or 0
        async for event in run_react_loop_streaming(
            paper_id=0, conv_id=conv_id, question=req.question,
            provider="deepseek", system_prompt=build_system_prompt(mode="agent"),
        ):
            etype = event.get("event", "")
            data = event.get("data", "")

            if etype == "status":
                yield _chunk("status", data)

            elif etype == "tool_call":
                tool = data.get("tool", "?") if isinstance(data, dict) else str(data)
                params = data.get("params", {}) if isinstance(data, dict) else {}
                yield _chunk("tool_call", {"tool": tool, "params": params})

            elif etype == "observation":
                obs = data if isinstance(data, str) else str(data)
                yield _chunk("observation", obs[:2000])

            elif etype == "content":
                token = data if isinstance(data, str) else data.get("token", "")
                if token:
                    yield _chunk("content", token)

            elif etype == "done":
                d = data if isinstance(data, dict) else {}
                yield _chunk("done", {
                    "conv_id": d.get("conv_id"),
                    "tool_trace": d.get("tool_trace", []),
                    "guard_result": d.get("guard_result", ""),
                })
                return

        yield _chunk("done", {})

    @classmethod
    def cancel(cls, conv_id: int) -> bool:
        """Signal cancellation for an active conversation. Returns True if found."""
        event = cls._active_cancels.get(conv_id)
        if event:
            event.set()
            return True
        return False


def _chunk(msg_type: str, content) -> bytes:
    payload = json.dumps({"type": msg_type, "content": content}, ensure_ascii=False)
    return (payload + END_OF_STREAM).encode("utf-8")
