"""Tool: compare papers with Semaphore(3) parallel LLM summarization."""

import json
import asyncio
from pathlib import Path
from typing import List, Dict

from data.db import PaperDB
from core.llm_router import router


async def compare(paper_ids: List[int], dimension: str = "method") -> str:
    """Fetch key sections and generate comparison. Parallel via asyncio."""
    db = PaperDB()
    try:
        papers = []
        for pid in paper_ids:
            p = db.get_paper(pid)
            if not p:
                continue
            qpath = Path(p.get("parsed_quick_path", ""))
            text = ""
            if qpath.exists():
                data = json.loads(qpath.read_text(encoding="utf-8"))
                text = data.get("full_text", "")[:4000]
            papers.append({"id": pid, "title": p.get("title", "Unknown"), "text": text})

        if len(papers) < 2:
            return "[Error: Need at least 2 papers to compare]"

        # Phase 1: Parallel summarization via Semaphore(3)
        return await _compare_parallel(papers, dimension)
    finally:
        db.close()


async def _compare_parallel(papers: List[Dict], dimension: str) -> str:
    """Parallel LLM calls with Semaphore(3) for JSON summaries."""
    sem = asyncio.Semaphore(3)

    async def _summarize(paper: Dict) -> Dict:
        async with sem:
            prompt = (
                f"Paper: {paper['title']}\n\n"
                f"Content (first 4000 chars):\n{paper['text']}\n\n"
                f"Extract structured JSON about the {dimension}:\n"
                '{"title": "...", "method": "...", "dataset": "...", "key_metrics": "...", "contribution": "..."}\n'
                "Respond ONLY with JSON."
            )
            text = ""
            async for token in router.complete(
                [{"role": "user", "content": prompt}],
                provider="deepseek", task_type="compare", max_tokens=500, max_retries=2,
            ):
                text += token
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"title": paper["title"], "method": text[:200]}

    summaries = await asyncio.gather(*[_summarize(p) for p in papers])

    # Phase 2: Build comparison table
    lines = [f"## Comparison: {dimension}\n"]
    lines.append("| Paper | " + " | ".join(s.get("method", "?")[:30] for s in summaries) + " |")
    lines.append("|" + "---|" * (len(summaries) + 1))

    for field, label in [("dataset", "Dataset"), ("key_metrics", "Metrics"), ("contribution", "Contribution")]:
        row = [label]
        for s in summaries:
            val = s.get(field, "") or ""
            row.append(str(val)[:50])
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines) + "\n\n[Structured comparison complete]"
