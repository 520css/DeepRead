"""Hallucination detection guard."""

import re
import json
from pathlib import Path
from typing import List, Dict, Tuple

from data.db import PaperDB
from core.embedder import embed_single
import numpy as np

SIMILARITY_THRESHOLD = 0.70


def verify_citations(paper_id: int, response_text: str, retrieved_chunks: List[Dict]) -> Tuple[bool, str]:
    """
    Check if citations [P.X] in response are backed by retrieved chunks.
    Returns (ok, warning_message).
    """
    cited_pages = set(re.findall(r"\[P\.(\d+)\]", response_text))
    if not cited_pages:
        # No citations requested, but for factual claims this is suspicious
        return True, ""

    chunk_pages = {str(c["page_number"]): c["content"] for c in retrieved_chunks}
    missing = [p for p in cited_pages if p not in chunk_pages]

    if missing:
        return False, f"⚠️ 引用验证失败: 页码 {', '.join(missing)} 不在检索片段中。可能为幻觉。"

    return True, ""


def verify_embedding_similarity(response_text: str, retrieved_chunks: List[Dict]) -> Tuple[bool, str]:
    """Check if response embedding is semantically close to retrieved chunks."""
    if not retrieved_chunks:
        return True, ""

    try:
        resp_emb = embed_single(response_text)
        chunk_embs = [embed_single(c["content"]) for c in retrieved_chunks]

        # Compute max cosine similarity
        max_sim = -1.0
        for ce in chunk_embs:
            sim = _cosine_sim(resp_emb, ce)
            if sim > max_sim:
                max_sim = sim

        if max_sim < SIMILARITY_THRESHOLD:
            return False, f"⚠️ 语义相似度偏低 ({max_sim:.2f} < {SIMILARITY_THRESHOLD})，回答可能与原文不符。"
        return True, f"✅ 语义相似度: {max_sim:.2f}"
    except Exception as e:
        return True, f"[嵌入验证跳过: {e}]"


def verify_numbers(response_text: str, paper_id: int) -> Tuple[bool, str]:
    """Spot-check if numbers in response appear in the paper text."""
    db = PaperDB()
    try:
        paper = db.get_paper(paper_id)
        if not paper:
            return True, ""
        qpath = Path(paper.get("parsed_quick_path", ""))
        if not qpath.exists():
            return True, ""
        data = json.loads(qpath.read_text(encoding="utf-8"))
        full_text = data.get("full_text", "")

        # Extract numbers (including decimals and percentages)
        nums = re.findall(r"\b\d+\.?\d*%?\b", response_text)
        suspicious = []
        for n in nums[:5]:  # Check first 5 numbers only
            if n not in full_text:
                suspicious.append(n)
        if suspicious:
            return False, f"⚠️ 数值验证: {', '.join(suspicious)} 未在原文中找到，请核对。"
        return True, ""
    finally:
        db.close()


def full_guard(paper_id: int, response_text: str, retrieved_chunks: List[Dict]) -> str:
    """Run all guards and return a combined status string."""
    results = []
    ok1, msg1 = verify_citations(paper_id, response_text, retrieved_chunks)
    if msg1:
        results.append(msg1)
    ok2, msg2 = verify_embedding_similarity(response_text, retrieved_chunks)
    if msg2:
        results.append(msg2)
    ok3, msg3 = verify_numbers(response_text, paper_id)
    if msg3:
        results.append(msg3)

    if not results:
        return ""
    return "\n\n".join(results)


def _cosine_sim(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))
