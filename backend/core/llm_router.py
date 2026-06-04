import os
import asyncio
from typing import AsyncGenerator, List, Dict
from datetime import datetime

import yaml
from dotenv import load_dotenv

load_dotenv()

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # paperbridge/

# Load config
with open(os.path.join(_ROOT, "config.yaml"), "r", encoding="utf-8") as f:
    _CFG = yaml.safe_load(f)

_providers = _CFG.get("llm", {}).get("providers", {})
_budget_cfg = _CFG.get("budget", {})


def _load_env_key(provider: str, config_key: str, env_var: str) -> str:
    """Load API key from env var first, then config file."""
    return os.environ.get(env_var) or _providers.get(provider, {}).get(config_key, "")


class LLMRouter:
    def __init__(self):
        self._semaphore = asyncio.Semaphore(5)
        self._clients = {}
        self._price_map = {}
        self._init_clients()

    def _init_clients(self):
        # Anthropic
        if "claude" in _providers:
            try:
                from anthropic import AsyncAnthropic
                key = _load_env_key("claude", "api_key", "CLAUDE_API_KEY")
                if key:
                    base = _providers["claude"].get("base_url")
                    kwargs = {"api_key": key}
                    if base:
                        kwargs["base_url"] = base
                    self._clients["claude"] = AsyncAnthropic(**kwargs)
                    self._price_map["claude"] = {
                        "input": _providers["claude"].get("input_price_per_1m", 3.0),
                        "output": _providers["claude"].get("output_price_per_1m", 15.0),
                    }
            except Exception as e:
                print(f"[LLM] Claude init failed: {e}")

        # OpenAI
        if "openai" in _providers:
            try:
                from openai import AsyncOpenAI
                key = _load_env_key("openai", "api_key", "OPENAI_API_KEY")
                if key:
                    base = _providers["openai"].get("base_url")
                    kwargs = {"api_key": key}
                    if base:
                        kwargs["base_url"] = base
                    self._clients["openai"] = AsyncOpenAI(**kwargs)
                    self._price_map["openai"] = {
                        "input": _providers["openai"].get("input_price_per_1m", 0.15),
                        "output": _providers["openai"].get("output_price_per_1m", 0.60),
                    }
            except Exception as e:
                print(f"[LLM] OpenAI init failed: {e}")

        # DeepSeek (OpenAI compatible)
        if "deepseek" in _providers:
            try:
                from openai import AsyncOpenAI
                key = _load_env_key("deepseek", "api_key", "DEEPSEEK_API_KEY")
                if key:
                    base = _providers["deepseek"].get("base_url", "https://api.deepseek.com")
                    self._clients["deepseek"] = AsyncOpenAI(api_key=key, base_url=base)
                    self._price_map["deepseek"] = {
                        "input": _providers["deepseek"].get("input_price_per_1m", 0.14),
                        "output": _providers["deepseek"].get("output_price_per_1m", 0.28),
                    }
            except Exception as e:
                print(f"[LLM] DeepSeek init failed: {e}")

    def _get_monthly_cost(self) -> float:
        from data.db import PaperDB
        db = PaperDB()
        try:
            return db.get_monthly_cost()
        finally:
            db.close()

    def _calc_cost(self, provider: str, input_tokens: int, output_tokens: int) -> float:
        prices = self._price_map.get(provider, {"input": 0, "output": 0})
        return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000

    def _normalize_provider(self, provider: str) -> str:
        """Map frontend provider names (deepseek-chat, claude-sonnet-4-6) to internal keys."""
        if not provider:
            return _CFG.get("llm", {}).get("default_provider", "deepseek")
        provider_lower = provider.lower()
        if "deepseek" in provider_lower:
            return "deepseek"
        if "claude" in provider_lower:
            return "claude"
        if "openai" in provider_lower or "gpt" in provider_lower:
            return "openai"
        return provider

    async def complete(
        self,
        messages: List[Dict],
        provider: str = None,
        model: str = None,
        stream: bool = True,
        task_type: str = "qa",
        max_retries: int = 3,
        conversation_id: int = None,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[str, None]:
        provider = self._normalize_provider(provider)
        model = model or _providers.get(provider, {}).get("model")

        # Budget check
        limit = _budget_cfg.get("monthly_limit_usd", 20.0)
        monthly_cost = self._get_monthly_cost()
        if monthly_cost >= limit:
            mode = _budget_cfg.get("on_exceed", "downgrade")
            if mode == "block":
                yield "[已超出月度预算，请在 config.yaml 中调整 budget 设置]"
                return
            elif mode == "downgrade":
                provider = "deepseek"
                model = _providers.get("deepseek", {}).get("model")
                yield "[预算超额，已自动降级到经济模型]\n\n"

        fallback_order = ["claude", "openai", "deepseek"]
        tried = []

        for p in [provider] + [f for f in fallback_order if f != provider and f in self._clients]:
            tried.append(p)
            for attempt in range(max_retries):
                try:
                    async with self._semaphore:
                        total_tokens = {"input": 0, "output": 0}
                        async for chunk in self._stream_provider(p, model, messages, max_tokens=max_tokens):
                            if isinstance(chunk, dict) and "usage" in chunk:
                                total_tokens = chunk["usage"]
                            else:
                                yield chunk

                        cost = self._calc_cost(p, total_tokens.get("input", 0), total_tokens.get("output", 0))
                        self._log_usage(p, model, task_type, total_tokens.get("input", 0), total_tokens.get("output", 0), cost, conversation_id)
                        return
                except Exception as e:
                    wait = 2 ** attempt
                    print(f"[LLM] {p} attempt {attempt + 1} failed: {e}, retry in {wait}s")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(wait)
                    continue

        yield f"[所有 LLM provider 均不可用: {', '.join(tried)}]"

    async def complete_single(
        self,
        messages: List[Dict],
        provider: str = None,
        model: str = None,
        task_type: str = "compaction",
        max_retries: int = 2,
        conversation_id: int = None,
        max_tokens: int = 1024,
    ) -> str:
        """Non-streaming completion for cheap tasks like compaction."""
        provider = provider or "deepseek"
        model = model or _providers.get(provider, {}).get("model")
        tried = []
        for p in [provider] + [f for f in ["deepseek", "openai", "claude"] if f != provider and f in self._clients]:
            tried.append(p)
            for attempt in range(max_retries):
                try:
                    async with self._semaphore:
                        text = ""
                        async for chunk in self._stream_provider(p, model, messages, max_tokens=max_tokens):
                            if not isinstance(chunk, dict):
                                text += chunk
                        # Rough token estimation for logging (no usage data in non-streaming fallback)
                        inp_tok = sum(len(m.get("content", "")) for m in messages) // 4
                        out_tok = len(text) // 4
                        cost = self._calc_cost(p, inp_tok, out_tok)
                        self._log_usage(p, model, task_type, inp_tok, out_tok, cost, conversation_id)
                        return text
                except Exception as e:
                    wait = 2 ** attempt
                    print(f"[LLM] {p} attempt {attempt + 1} failed: {e}, retry in {wait}s")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(wait)
                    continue
        return "[Compaction failed: all providers unavailable]"

    async def _stream_provider(self, provider: str, model: str, messages: List[Dict], max_tokens: int = 4096):
        client = self._clients.get(provider)
        if not client:
            raise ValueError(f"Provider {provider} not initialized")

        system_msg = None
        user_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_msg = m.get("content", "")
            else:
                user_messages.append(m)

        if provider == "claude":
            kwargs = {
                "model": model,
                "messages": user_messages,
                "max_tokens": max_tokens,
            }
            if system_msg:
                kwargs["system"] = system_msg

            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                        yield event.delta.text
        else:
            # OpenAI compatible (OpenAI, DeepSeek, etc.)
            msgs = []
            if system_msg:
                msgs.append({"role": "system", "content": system_msg})
            msgs.extend(user_messages)

            response = await client.chat.completions.create(
                model=model,
                messages=msgs,
                stream=True,
                max_tokens=max_tokens,
                stream_options={"include_usage": True},
            )
            inp_tokens = 0
            out_tokens = 0
            try:
                async for chunk in response:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                    if hasattr(chunk, 'usage') and chunk.usage:
                        inp_tokens = chunk.usage.prompt_tokens or 0
                        out_tokens = chunk.usage.completion_tokens or 0
            except TypeError:
                # Fallback for sync Stream objects
                for chunk in response:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                    if hasattr(chunk, 'usage') and chunk.usage:
                        inp_tokens = chunk.usage.prompt_tokens or 0
                        out_tokens = chunk.usage.completion_tokens or 0
            yield {"usage": {"input": inp_tokens, "output": out_tokens}}

    def _log_usage(self, provider, model, task_type, input_tokens, output_tokens, cost_usd, conversation_id=None):
        from data.db import PaperDB
        db = PaperDB()
        try:
            db.log_usage(provider, model, task_type, input_tokens, output_tokens, cost_usd, conversation_id)
        finally:
            db.close()

    async def stats(self) -> str:
        from data.db import PaperDB
        db = PaperDB()
        try:
            total = db.get_monthly_cost()
            limit = _budget_cfg.get("monthly_limit_usd", 20.0)
            rows = db.conn.execute(
                """SELECT provider, COALESCE(SUM(cost_usd), 0) as cost,
                          SUM(input_tokens) as inp, SUM(output_tokens) as out
                   FROM llm_usage
                   WHERE strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now')
                   GROUP BY provider"""
            ).fetchall()
            lines = [f"本月用量总计: ${total:.2f} / ${limit:.2f}"]
            for r in rows:
                lines.append(f"  - {r['provider']}: {r['inp'] / 1000:.0f}K in / {r['out'] / 1000:.0f}K out = ${r['cost']:.2f}")
            return "\n".join(lines)
        finally:
            db.close()


# Singleton
router = LLMRouter()
