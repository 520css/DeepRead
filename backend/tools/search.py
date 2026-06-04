"""Tool: semantic search over local paper library via ChromaDB embeddings."""

from typing import List, Dict
from data.db import PaperDB
from core.embedder import embed_single
from core.rag import _get_collection


def search(query: str, scope: str = "global", paper_ids: list = None) -> List[Dict]:
    """Semantic search local papers. scope: global / recent. paper_ids: filter to specific papers."""
    db = PaperDB()
    try:
        papers = db.list_papers()
        if paper_ids:
            papers = [p for p in papers if p["id"] in paper_ids]
        if not papers:
            return []

        if scope == "recent":
            papers = papers[:10]

        # ChromaDB semantic search across all paper chunks
        try:
            collection = _get_collection()
            if collection.count() > 0:
                query_emb = embed_single(query)
                results = collection.query(
                    query_embeddings=[query_emb],
                    n_results=20,
                )
                # Aggregate by paper_id with max similarity
                scored: Dict[int, float] = {}
                for i in range(len(results["ids"][0])):
                    meta = results["metadatas"][0][i]
                    pid = meta.get("paper_id")
                    dist = results["distances"][0][i]
                    sim = 1.0 - dist  # ChromaDB returns distance, convert to similarity
                    if pid not in scored or sim > scored[pid]:
                        scored[pid] = sim

                # Return papers sorted by similarity
                result_papers = []
                for p in papers:
                    pid = p["id"]
                    if pid in scored:
                        p = dict(p)
                        p["_score"] = round(scored[pid], 3)
                        result_papers.append(p)
                result_papers.sort(key=lambda x: x["_score"], reverse=True)
                return result_papers[:15]
        except Exception:
            pass

        # Fallback: keyword search
        query_lower = query.lower()
        results = []
        for p in papers:
            text = f"{p.get('title', '')} {p.get('abstract', '')}"
            if query_lower in text.lower():
                results.append(p)
        return results[:10]
    finally:
        db.close()
