"""Recommendation service: similar papers, arXiv feed, forgotten papers.

All recommendations are user-triggered (no background cron).
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Optional

from data.db import PaperDB

# paperbridge/ root
_ROOT = Path(__file__).resolve().parent.parent.parent

# Simple in-memory cache (TTL in seconds)
_cache: Dict[str, tuple] = {}  # key → (data, expiry_timestamp)


class RecommendService:
    """Service for paper recommendations and discovery."""

    def __init__(self):
        self.db = PaperDB()

    # ─── Similar Papers (local, via ChromaDB embeddings) ───

    async def similar_papers(self, paper_id: int, limit: int = 5) -> List[dict]:
        """Find similar papers in the local library using embedding similarity."""
        try:
            from core.embedder import embed_single
            import chromadb
            from chromadb.config import Settings

            paper = self.db.get_paper(paper_id)
            if not paper:
                return []

            # Get paper abstract as query
            query_text = paper.get("abstract") or paper.get("title") or ""
            if not query_text:
                return []

            # Search ChromaDB
            client = chromadb.PersistentClient(
                path=str(_ROOT / "storage" / "chroma_data"),
                settings=Settings(anonymized_telemetry=False),
            )
            collection = client.get_or_create_collection("paper_chunks")
            query_emb = embed_single(query_text)

            results = collection.query(
                query_embeddings=[query_emb],
                n_results=limit * 3,  # Oversample to filter duplicates
            )

            # Collect unique paper IDs
            seen = {paper_id}
            similar = []
            for i in range(len(results["ids"][0])):
                meta = results["metadatas"][0][i]
                pid = meta.get("paper_id")
                if pid and pid not in seen:
                    seen.add(pid)
                    p = self.db.get_paper(pid)
                    if p:
                        similar.append(p)
                if len(similar) >= limit:
                    break

            return similar
        except Exception as e:
            print(f"[RecommendService] similar_papers failed: {e}")
            return []

    # ─── arXiv New Papers (external API, cached 30 min) ───

    async def arxiv_feed(self, days: int = 7, interests: Optional[List[str]] = None) -> List[dict]:
        """Fetch recent papers from arXiv matching interests (cached 30 min)."""
        cache_key = f"arxiv:{days}:{','.join(sorted(interests or []))}"
        if cached := _cache_get(cache_key):
            return cached

        results = []
        if interests:
            for interest in interests[:3]:  # Limit to 3 queries to avoid rate limiting
                try:
                    papers = await _fetch_arxiv(interest, max_results=5, sort_by="submittedDate")
                    results.extend(papers)
                except Exception as e:
                    print(f"[RecommendService] arXiv fetch failed for '{interest}': {e}")

        # Dedup by arxiv_id
        seen = set()
        deduped = []
        for r in results:
            aid = r.get("arxiv_id")
            if aid and aid not in seen:
                seen.add(aid)
                deduped.append(r)

        _cache_set(cache_key, deduped, ttl=1800)
        return deduped

    # ─── Forgotten Papers (local, based on read timestamps) ───

    async def forgotten_papers(self, limit: int = 10) -> List[dict]:
        """Find papers that haven't been interacted with recently."""
        rows = self.db.conn.execute(
            """SELECT p.* FROM papers p
               LEFT JOIN (
                   SELECT conv.paper_id, MAX(m.created_at) as last_read
                   FROM messages m
                   JOIN conversations conv ON m.conversation_id = conv.id
                   GROUP BY conv.paper_id
               ) mr ON p.id = mr.paper_id
               WHERE mr.last_read IS NULL
                  OR mr.last_read < datetime('now', '-30 days')
               ORDER BY p.added_at DESC
               LIMIT ?""",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.db.close()


# ─── arXiv API helper ───

async def _fetch_arxiv(query: str, max_results: int = 5, sort_by: str = "relevance") -> List[dict]:
    """Fetch papers from arXiv API via the arxiv package."""
    import arxiv

    sort_criterion = arxiv.SortCriterion.Relevance if sort_by == "relevance" else arxiv.SortCriterion.SubmittedDate
    search = arxiv.Search(query=query, max_results=max_results, sort_by=sort_criterion)
    client = arxiv.Client()

    papers = []
    for r in client.results(search):
        papers.append({
            "title": (r.title or "").strip().replace("\n", " "),
            "abstract": (r.summary or "").strip()[:500],
            "authors": ", ".join(str(a) for a in r.authors),
            "arxiv_id": r.entry_id.split("/")[-1],
            "published": str(r.published) if r.published else "",
            "source": "arxiv",
        })
    return papers


# ─── Simple cache ───

def _cache_get(key: str) -> Optional[List[dict]]:
    if key in _cache:
        data, expiry = _cache[key]
        if time.time() < expiry:
            return data
        del _cache[key]
    return None


def _cache_set(key: str, data: List[dict], ttl: int):
    _cache[key] = (data, time.time() + ttl)
