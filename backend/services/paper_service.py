"""Paper service: CRUD, dual-track parse orchestration, dedup, and metadata completion."""

import hashlib
import shutil
import asyncio
import threading
from pathlib import Path
from typing import Optional, List, Dict

from data.db import PaperDB
from core.parser import DocumentParser


def _run_async_in_thread(coro):
    """Run an async coroutine from a sync background thread."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            new_loop = asyncio.new_event_loop()
            return new_loop.run_until_complete(coro)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)

# paperbridge/ root (for storage/)
_ROOT = Path(__file__).resolve().parent.parent.parent
PAPERS_DIR = _ROOT / "storage" / "papers"
PAPERS_DIR.mkdir(parents=True, exist_ok=True)

_parser = DocumentParser()


class PaperService:
    """Service layer for paper operations."""

    def __init__(self):
        self.db = PaperDB()
        self.parser = _parser

    # ─── Upload ───

    def upload_pdf(self, file_data: bytes, filename: str) -> dict:
        """
        Upload a PDF file: save, SHA256 hash, Quick parse, return paper info.
        Verified parse runs async in background.
        """
        # 1. Save file
        pdf_hash = hashlib.sha256(file_data).hexdigest()
        file_path = PAPERS_DIR / f"{pdf_hash}.pdf"

        if not file_path.exists():
            file_path.write_bytes(file_data)

        # 2. Dedup check
        existing = self.db.get_paper_by_hash(pdf_hash)
        if existing:
            return {
                "paper_id": existing["id"],
                "hash": pdf_hash,
                "status": "existing",
                "parse_status": existing.get("parse_status", "quick"),
            }

        # 3. Quick parse (PyMuPDF, synchronous, ~5-10s)
        result = self.parser.parse(str(file_path))

        # 3.5 Extract PDF metadata (title, author, year, abstract)
        meta = self._extract_pdf_metadata(str(file_path))
        title = meta.get("title") or filename.rsplit(".", 1)[0]
        authors = meta.get("author", "")
        year = meta.get("year")
        abstract = meta.get("abstract", "")

        # 4. Store in DB
        paper_id = self.db.add_paper(
            title=title,
            authors=authors,
            year=year,
            abstract=abstract,
            keywords="",
            doi=None,
            arxiv_id=None,
            file_path=str(file_path),
            parsed_quick_path=str(_ROOT / "storage" / "parsed" / f"{pdf_hash}.quick.json"),
            parsed_verified_path="",
            parse_status=result.get("quality", "quick"),
            source="upload",
            paper_hash=pdf_hash,
        )

        # 5. Background tasks: ChromaDB index + summary generation + verified parse
        pages = result.get("pages", [])
        full_text = result.get("full_text", "")
        threading.Thread(target=self._index_background, args=(paper_id, pages), daemon=True).start()
        threading.Thread(target=self._summary_background, args=(paper_id, full_text), daemon=True).start()

        return {
            "paper_id": paper_id,
            "hash": pdf_hash,
            "status": "created",
            "parse_status": result.get("quality", "quick"),
            "message": "Quick parse complete. Summary & indexing started.",
        }

    # ─── CRUD ───

    def get_paper(self, paper_id: int) -> Optional[dict]:
        paper = self.db.get_paper(paper_id)
        if not paper:
            return None
        return self._enrich_paper(paper)

    def list_papers(self) -> List[dict]:
        papers = self.db.list_papers()
        return [self._enrich_paper(p) for p in papers]

    def update_paper(self, paper_id: int, **kwargs) -> Optional[dict]:
        self.db.update_paper_metadata(paper_id, **kwargs)
        self.db.set_user_modified(paper_id, True)
        return self.get_paper(paper_id)

    def get_paper_status(self, paper_id: int) -> dict:
        paper = self.db.get_paper(paper_id)
        if not paper:
            return {"status": "not_found"}
        return {
            "paper_id": paper_id,
            "parse_status": paper.get("parse_status", "pending"),
            "user_modified": bool(paper.get("user_modified")),
        }

    def close(self):
        self.db.close()

    # ─── Helpers ───

    def _extract_pdf_metadata(self, file_path: str) -> dict:
        """Extract title, author, year, abstract from PDF — first from PDF meta, then first-page text."""
        meta = {}
        try:
            import fitz, re
            doc = fitz.open(file_path)
            pdf_meta = doc.metadata or {}
            first_text = doc[0].get_text()[:3000] if len(doc) > 0 else ""

            # Title: prefer PDF meta, fall back to first non-empty line
            title = (pdf_meta.get("title") or "").strip()
            if not title or len(title) < 5:
                lines = [l.strip() for l in first_text.split("\n") if l.strip()]
                for l in lines[:10]:
                    if len(l) > 10 and not l.lower().startswith(("abstract", "introduction", "arxiv", "figure", "table", "http")):
                        title = l
                        break
            meta["title"] = title.replace("\n", " ")[:300]

            # Author: prefer PDF meta, fall back to text after title
            author = (pdf_meta.get("author") or "").strip()
            if not author:
                lines = first_text.split("\n")
                for i, l in enumerate(lines):
                    if title[:30] in l and i + 1 < len(lines):
                        candidate = lines[i + 1].strip()
                        if candidate and len(candidate) < 200:
                            author = candidate
                            break
            meta["author"] = author.replace("\n", ", ")[:500]

            # Year: try metadata date, then first page for arXiv/date patterns
            year = None
            creation = pdf_meta.get("creationDate", "")
            for source in [creation, first_text[:1000]]:
                if year: break
                patterns = [
                    r"arXiv.*?(\d{4})",           # arXiv:2409.12191 → 2024
                    r"(?:19|20)\d{2}",             # any year
                ]
                for pat in patterns:
                    m = re.search(pat, source)
                    if m:
                        y = int(m.group(1))
                        if 1990 <= y <= 2030:
                            year = y
                            break
            meta["year"] = year

            # Abstract: try to find text between "Abstract" and "Introduction"/"1."
            abstract = ""
            abs_match = re.search(r"Abstract\s*\n(.*?)(?:\n\s*(?:1[.\s]|I[.\s]|Introduction|$))", first_text, re.DOTALL | re.IGNORECASE)
            if abs_match:
                abstract = abs_match.group(1).strip()[:2000]
            meta["abstract"] = abstract

            doc.close()
        except Exception:
            pass
        return meta

    def _summary_background(self, paper_id: int, full_text: str):
        """Generate structured summary via LLM in background."""
        try:
            if len(full_text) < 200:
                return
            from core.llm_router import router
            import json

            # Send first 8000 chars — covers abstract, intro, method, and usually early findings.
            # Avoids the ending (typically references/appendix — useless for summarization).
            paper_snippet = full_text[:8000]

            prompt = (
                "You are a research assistant. Generate a structured Chinese summary based on this paper content.\n\n"
                f"Paper text:\n{paper_snippet}\n\n"
                "Output JSON (Chinese):\n"
                '{"one_liner": "一句话概括", "contributions": ["贡献1", "贡献2", "贡献3"], '
                '"method": "方法简述", "key_findings": ["发现1", "发现2"], "takeaway": "关键启示"}\n'
                "Respond ONLY with JSON, no other text."
            )
            try:
                response = _run_async_in_thread(
                    router.complete_single(
                        [{"role": "user", "content": prompt}],
                        provider="deepseek", task_type="summary", max_tokens=800, max_retries=2,
                    )
                )
            except Exception:
                response = ""

            if response:
                import re
                try:
                    summary = json.loads(response)
                except json.JSONDecodeError:
                    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response)
                    if match:
                        try:
                            summary = json.loads(match.group(1))
                        except json.JSONDecodeError:
                            summary = {"raw": response}
                    else:
                        summary = {"raw": response}

                summary_md = self._format_summary_markdown(summary, full_text)
                self.db.conn.execute(
                    "UPDATE papers SET summary = ? WHERE id = ?",
                    (summary_md, paper_id)
                )
                self.db.conn.commit()
                print(f"[PaperService] Summary generated for paper {paper_id}")
            else:
                # Fallback: show first page as summary
                self.db.conn.execute(
                    "UPDATE papers SET summary = ? WHERE id = ?",
                    (full_text[:3000] + "\n\n*(AI summary generation failed — showing raw text)*", paper_id)
                )
                self.db.conn.commit()
        except Exception as e:
            print(f"[PaperService] Summary generation failed: {e}")
            try:
                self.db.conn.execute(
                    "UPDATE papers SET summary = ? WHERE id = ?",
                    (full_text[:3000] + "\n\n*(Summary unavailable)*", paper_id)
                )
                self.db.conn.commit()
            except Exception:
                pass

    @staticmethod
    def _format_summary_markdown(summary: dict, full_text: str) -> str:
        md = []
        if "one_liner" in summary:
            md.append(f"## 速读\n\n{summary['one_liner']}")
        if "contributions" in summary and isinstance(summary["contributions"], list):
            md.append("## 核心贡献\n")
            for c in summary["contributions"]:
                md.append(f"- {c}")
        if "method" in summary:
            md.append(f"\n## 方法\n\n{summary['method']}")
        if "key_findings" in summary and isinstance(summary["key_findings"], list):
            md.append("\n## 关键发现\n")
            for f in summary["key_findings"]:
                md.append(f"- {f}")
        if "takeaway" in summary:
            md.append(f"\n---\n\n**💡 {summary['takeaway']}**")
        md.append(f"\n\n---\n*AI-generated summary • {len(full_text):,} chars parsed*")
        return "\n".join(md)

    def _index_background(self, paper_id: int, pages: list):
        """Background ChromaDB indexing (embedding model loads lazily, first call is slow)."""
        try:
            from core.rag import index_paper
            n = index_paper(paper_id, pages)
            print(f"[PaperService] ChromaDB indexed {n} chunks for paper {paper_id}")
        except Exception as e:
            print(f"[PaperService] ChromaDB index failed for paper {paper_id}: {e}")

    def _enrich_paper(self, paper: dict) -> dict:
        """Add computed fields to paper dict before returning."""
        # Generate summary from quick parse if available
        qp = paper.get("parsed_quick_path", "")
        if qp and Path(qp).exists():
            paper["_has_quick_parse"] = True
        vp = paper.get("parsed_verified_path", "")
        if vp and Path(vp).exists():
            paper["_has_verified_parse"] = True
        return paper
