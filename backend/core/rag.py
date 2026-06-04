"""RAG: smart chunking, ChromaDB indexing, retrieval, re-indexing."""

import re
from typing import List, Dict
from pathlib import Path
import chromadb
from chromadb.config import Settings

from core import embedder
from data.db import PaperDB

_ROOT = Path(__file__).resolve().parent.parent.parent  # paperbridge/
_CHROMA_CLIENT = None
_COLLECTION = None


def _get_collection():
    global _CHROMA_CLIENT, _COLLECTION
    if _CHROMA_CLIENT is None:
        _CHROMA_CLIENT = chromadb.PersistentClient(
            path=str(_ROOT / "storage" / "chroma_data"),
            settings=Settings(anonymized_telemetry=False),
        )
        _COLLECTION = _CHROMA_CLIENT.get_or_create_collection("paper_chunks")
    return _COLLECTION


# ═══════════════════════════════════════════════════════════════
# Smart chunking
# ═══════════════════════════════════════════════════════════════

def smart_chunk(text: str, max_tokens: int = 512) -> List[Dict]:
    """
    Intelligent chunking: paragraph → sentence → sliding window.
    max_tokens is approximated as chars/3.5 for mixed Chinese-English.
    """
    max_chars = max_tokens * 3.5
    chunks = []

    # Step 1: Split by paragraphs (double newline)
    paragraphs = re.split(r"\n\s*\n", text)

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if _est_tokens(para) <= max_tokens:
            chunks.append({"text": para})
        else:
            # Step 2: Split long paragraph by sentences
            sentences = _split_sentences(para)
            current = ""
            for sent in sentences:
                if _est_tokens(current + sent) <= max_tokens:
                    current += sent
                else:
                    if current.strip():
                        chunks.append({"text": current.strip()})
                    # Step 3: If single sentence still too long → sliding window
                    if _est_tokens(sent) > max_tokens:
                        for sub in _sliding_window(sent, max_chars):
                            chunks.append({"text": sub.strip()})
                        current = ""
                    else:
                        current = sent
            if current.strip():
                chunks.append({"text": current.strip()})

    # Add overlap: prepend last sentence of previous chunk to next chunk
    result = []
    prev_last_sent = ""
    for c in chunks:
        text = c["text"]
        if prev_last_sent and prev_last_sent not in text[:len(prev_last_sent)]:
            text = prev_last_sent + " " + text
        result.append({"text": text})
        sent_end = _split_sentences(text)
        prev_last_sent = sent_end[-1] if sent_end else ""

    return result


def _est_tokens(text: str) -> int:
    """Approximate token count for mixed Chinese-English text."""
    return max(1, len(text) // 3)


def _split_sentences(text: str) -> List[str]:
    """Split text by sentence boundaries."""
    parts = re.split(r"(?<=[。！？.!?])\s*", text)
    return [p for p in parts if p.strip()]


def _sliding_window(text: str, max_chars: int) -> List[str]:
    """Fallback: fixed-size sliding window with hard caps to prevent OOM."""
    chunks = []
    text_len = len(text)
    # Safety: if text is unusually long, use simple fixed splits (no overlap)
    # Lowered threshold: > 20x max_chars triggers safe path
    if text_len > max_chars * 20:
        step = max(int(max_chars * 0.85), 1)
        start = 0
        while start < text_len and len(chunks) < 500:
            end = min(start + int(max_chars), text_len)
            chunks.append(text[start:end])
            start += step
        return chunks
    # Normal sliding window with overlap (hard cap at 500 iterations)
    start = 0
    iterations = 0
    overlap = max(int(max_chars * 0.15), 1)
    while start < text_len and iterations < 500:
        end = min(start + int(max_chars), text_len)
        chunks.append(text[start:end])
        start = end - overlap
        iterations += 1
    return chunks


# ═══════════════════════════════════════════════════════════════
# ChromaDB + SQLite indexing
# ═══════════════════════════════════════════════════════════════

def index_paper(paper_id: int, pages: List[Dict]) -> int:
    """Smart-chunk paper pages and add to ChromaDB + SQLite. Capped per page to prevent OOM."""
    collection = _get_collection()
    db = PaperDB()
    all_chunks = []

    paper = db.get_paper(paper_id)
    title_prefix = f"[{paper['title']}] " if paper and paper.get("title") else ""

    MAX_CHUNKS_PER_PAGE = 80  # hard cap: absurdly dense pages should not blow up memory

    for page in pages:
        text = page.get("text", "")
        page_num = page.get("page", 1)
        chunks = smart_chunk(text)
        # Cap: if a page produces way too many chunks, keep the largest ones
        if len(chunks) > MAX_CHUNKS_PER_PAGE:
            chunks.sort(key=lambda c: len(c["text"]), reverse=True)
            chunks = chunks[:MAX_CHUNKS_PER_PAGE]
        for i, ch in enumerate(chunks):
            all_chunks.append({
                "paper_id": paper_id,
                "page_number": page_num,
                "chunk_index": i,
                "content": title_prefix + ch["text"],
            })

    if not all_chunks:
        db.close()
        return 0

    # ChromaDB — batch embed in groups of 100 to avoid OOM
    texts = [c["content"] for c in all_chunks]
    ids = [f"{paper_id}_{i}" for i in range(len(all_chunks))]
    metadatas = [{
        "paper_id": c["paper_id"],
        "page_number": c["page_number"],
        "chunk_index": c["chunk_index"],
        "title": paper.get("title", "") if paper else "",
        "authors": paper.get("authors", "") if paper else "",
    } for c in all_chunks]

    BATCH_SIZE = 100
    for batch_start in range(0, len(texts), BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, len(texts))
        batch_embeddings = embedder.embed(texts[batch_start:batch_end])
        collection.add(
            ids=ids[batch_start:batch_end],
            embeddings=batch_embeddings,
            documents=texts[batch_start:batch_end],
            metadatas=metadatas[batch_start:batch_end],
        )

    # SQLite
    for c in all_chunks:
        db.add_chunk(c["paper_id"], c["page_number"], "", c["content"], f"{paper_id}_{c['chunk_index']}")
    db.close()
    return len(all_chunks)


def delete_paper_chunks(paper_id: int):
    """Remove all chunks for a paper from ChromaDB and SQLite."""
    collection = _get_collection()
    try:
        collection.delete(where={"paper_id": paper_id})
    except Exception:
        pass
    db = PaperDB()
    try:
        db.conn.execute("DELETE FROM chunks WHERE paper_id = ?", (paper_id,))
        db.conn.commit()
    finally:
        db.close()


def reindex_paper(paper_id: int, pages: List[Dict]) -> int:
    """Delete old chunks, then re-index with smart chunking."""
    delete_paper_chunks(paper_id)
    return index_paper(paper_id, pages)


# ═══════════════════════════════════════════════════════════════
# Reranker (lazy-loaded from local cache)
# ═══════════════════════════════════════════════════════════════

_RERANKER_MODEL = None
_RERANKER_TOKENIZER = None
RERANKER_PATH = "BAAI/bge-reranker-v2-m3"


def _get_reranker():
    global _RERANKER_MODEL, _RERANKER_TOKENIZER
    if _RERANKER_MODEL is None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        _RERANKER_TOKENIZER = AutoTokenizer.from_pretrained(RERANKER_PATH, local_files_only=True)
        _RERANKER_MODEL = AutoModelForSequenceClassification.from_pretrained(RERANKER_PATH, local_files_only=True)
        _RERANKER_MODEL.eval()
    return _RERANKER_MODEL, _RERANKER_TOKENIZER


def _rerank(query: str, chunks: List[Dict], top_k: int = 5) -> List[Dict]:
    """Cross-encoder rerank. chunks must have 'content' key."""
    if len(chunks) <= top_k:
        return chunks
    import torch
    model, tokenizer = _get_reranker()
    pairs = [[query, c["content"]] for c in chunks]
    inputs = tokenizer(pairs, padding=True, truncation=True, max_length=512, return_tensors="pt")
    with torch.no_grad():
        scores = model(**inputs, return_dict=True).logits.view(-1)
    scored = sorted(zip(chunks, scores.tolist()), key=lambda x: x[1], reverse=True)
    return [c for c, _ in scored[:top_k]]


# ═══════════════════════════════════════════════════════════════
# Retrieval
# ═══════════════════════════════════════════════════════════════

def retrieve(paper_id: int, query: str, top_k: int = 5) -> List[Dict]:
    """Retrieve chunks: rough recall top-20 → rerank to top_k."""
    try:
        collection = _get_collection()
        if collection.count() == 0:
            return []
    except Exception:
        return []

    try:
        query_embedding = embedder.embed_single(query)
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(20, collection.count()),
            where={"paper_id": paper_id},
        )
        chunks = []
        for i in range(len(results["ids"][0])):
            meta = results["metadatas"][0][i]
            chunks.append({
                "id": results["ids"][0][i],
                "content": results["documents"][0][i],
                "page_number": meta.get("page_number", 1),
                "distance": results["distances"][0][i],
            })

        if len(chunks) > top_k:
            chunks = _rerank(query, chunks, top_k)
        return chunks
    except Exception:
        return []
