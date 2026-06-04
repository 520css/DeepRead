import hashlib
import json
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

_ROOT = Path(__file__).resolve().parent.parent.parent  # paperbridge/
CACHE_DIR = _ROOT / "storage" / "parsed"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
_verified_executor = ThreadPoolExecutor(max_workers=1)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def pymupdf_parse(file_path: str) -> dict:
    """Quick 解析：PyMuPDF 秒级提取纯文本"""
    if fitz is None:
        raise ImportError("PyMuPDF not installed")
    doc = fitz.open(file_path)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text().strip()
        if text:
            pages.append({"page": i + 1, "text": text})
    doc.close()
    return {
        "pages": pages,
        "full_text": "\n\n".join(p["text"] for p in pages),
    }


def _mineru_parse_sync(file_path: str) -> dict:
    """Verified 解析：MinerU CLI (mineru -p input -o output)"""
    import subprocess, shutil
    try:
        tmp_dir = CACHE_DIR / "_mineru_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["mineru", "-p", file_path, "-o", str(tmp_dir)],
            capture_output=True, text=True, timeout=900,
            env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"},
        )
        if result.returncode != 0:
            raise RuntimeError(f"MinerU CLI failed: {result.stderr[:500]}")

        # MinerU output: {tmp_dir}/{pdf_name}/{pdf_name}.md + images/
        md_files = list(tmp_dir.rglob("*.md"))
        if not md_files:
            raise RuntimeError("MinerU produced no .md output")
        md_path = md_files[0]
        text = md_path.read_text(encoding="utf-8")

        # Move images to parsed/images/ and fix Markdown paths
        img_src_dir = md_path.parent / "images"
        img_dst_dir = CACHE_DIR / "images"
        img_dst_dir.mkdir(parents=True, exist_ok=True)
        if img_src_dir.exists():
            for img in img_src_dir.iterdir():
                shutil.move(str(img), str(img_dst_dir / img.name))
            text = text.replace("images/", "http://localhost:8000/api/file/images/")

        shutil.rmtree(tmp_dir, ignore_errors=True)
        return {"pages": [{"page": 1, "text": text}], "full_text": text}
    except Exception as e:
        raise RuntimeError(f"MinerU parse failed: {e}")


def _marker_parse_sync(file_path: str, pdf_hash: str = "") -> dict:
    """Verified 解析：Marker PdfConverter with paginated markdown output."""
    import os as _os
    _os.environ.setdefault("TORCH_DEVICE", "cpu")  # CPU-only: prevent meta→cuda error

    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.config.parser import ConfigParser
    import re as _re

    # Use markdown output with pagination to get per-page structure with page markers
    config = {"output_format": "markdown", "paginate_output": True, "device": "cpu"}
    config_parser = ConfigParser(config)

    converter = PdfConverter(
        config=config_parser.generate_config_dict(),
        artifact_dict=create_model_dict(),
        processor_list=config_parser.get_processors(),
        renderer=config_parser.get_renderer(),
    )
    rendered = converter(file_path)

    # rendered.children is a list of page blocks when output_format="json"
    pages = []
    full_text_parts = []
    # Marker renders JSON as a MarkdownOutput with .markdown containing the paginated text
    paginated_md = getattr(rendered, "markdown", "") or ""

    # Parse paginated markdown: {0}----...\n\n{content}{1}----...\n\n{content}...
    if paginated_md:
        # Split by page markers: {N} followed by dashes
        page_blocks = _re.split(r"\{(\d+)\}\s*-{10,}\s*", paginated_md)
        # First element is text before any page marker (usually empty whitespace)
        if page_blocks and not page_blocks[0].strip():
            page_blocks = page_blocks[1:]
        # Now we have pairs: [page_num, content, page_num, content, ...]
        for i in range(0, len(page_blocks) - 1, 2):
            try:
                page_num = int(page_blocks[i]) + 1  # Marker uses 0-indexed pages
                content = page_blocks[i + 1].strip()
                if content:
                    pages.append({"page": page_num, "text": content})
                    full_text_parts.append(content)
            except (ValueError, IndexError):
                pass

    # Fallback: if pagination produced no pages, use the whole text as one page
    if not pages:
        text = paginated_md or getattr(rendered, "markdown", "") or str(rendered)
        pages = [{"page": 1, "text": text}]
        full_text_parts = [text]

    full_text = "\n\n".join(full_text_parts)

    # Save images and replace paths in Markdown
    images = rendered.images if hasattr(rendered, "images") and rendered.images else {}
    img_dir = CACHE_DIR / "images" / pdf_hash if pdf_hash else CACHE_DIR / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    base_url = f"http://localhost:8000/api/file/images/{pdf_hash}/" if pdf_hash else "http://localhost:8000/api/file/images/"
    for fname, pil_img in images.items():
        try:
            if hasattr(pil_img, "save"):
                safe_name = fname.replace("\\", "/").split("/")[-1]
                pil_img.save(str(img_dir / safe_name), "PNG")
                full_text = full_text.replace(fname, f"{base_url}{safe_name}")
                for p in pages:
                    p["text"] = p["text"].replace(fname, f"{base_url}{safe_name}")
        except Exception:
            pass

    return {"pages": pages, "full_text": full_text}


def _block_to_markdown(block, img_dir=None, img_counter=None, page_num=0) -> str:
    """Convert a Marker block to Markdown string."""
    block_type = getattr(block, "block_type", None)
    if block_type is None:
        return ""

    # Try to get raw text/html from block
    raw_text = getattr(block, "raw_text", "") or getattr(block, "text", "") or ""
    html = getattr(block, "html", "") or getattr(block, "rendered_html", "") or ""
    content = raw_text or html or ""

    bt = str(block_type).lower()

    # Section headers
    if "section" in bt or "header" in bt:
        level = getattr(block, "heading_level", 2) or 2
        prefix = "#" * min(level, 4)
        return f"{prefix} {content}"

    # Tables — render as Markdown table
    if "table" in bt:
        rows = getattr(block, "rows", []) or []
        if not rows:
            return content
        md_rows = []
        for ri, row in enumerate(rows):
            cells = getattr(row, "cells", []) or []
            cell_texts = [getattr(c, "text", "") or getattr(c, "raw_text", "") or "" for c in cells]
            md_rows.append("| " + " | ".join(cell_texts) + " |")
            if ri == 0:
                md_rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
        return "\n".join(md_rows)

    # Formulas / Equations
    if "equation" in bt or "formula" in bt or "math" in bt:
        formula = content.strip()
        if formula:
            return f"$$\n{formula}\n$$"
        return ""

    # Inline math
    if "inlinemath" in bt:
        return f"${content}$"

    # Code blocks
    if "code" in bt:
        lang = getattr(block, "language", "") or ""
        return f"```{lang}\n{content}\n```"

    # Lists
    if "listitem" in bt:
        return f"- {content}"

    # Figures / Pictures — save image to disk
    if "figure" in bt or "picture" in bt:
        caption = getattr(block, "caption", "") or ""
        alt = caption or "Figure"
        # Try to save the image
        img_path = ""
        if img_dir and img_counter is not None:
            for attr in ("highres_image", "lowres_image", "image"):
                img = getattr(block, attr, None)
                if img is not None and hasattr(img, "save"):
                    idx = img_counter[0]
                    img_counter[0] += 1
                    fname = f"page{page_num}_{idx}.png"
                    dest = img_dir / fname
                    try:
                        img.save(str(dest), "PNG")
                        # Relative path from storage/parsed/
                        img_path = f"http://localhost:8000/api/file/images/{img_dir.name}/{fname}"
                    except Exception:
                        pass
                    break
        if img_path:
            return f"![{alt}]({img_path})"
        return f"![{alt}](figure_p{getattr(block, 'page_id', '')})"

    # Captions
    if "caption" in bt:
        return f"*{content}*"

    # Footnotes
    if "footnote" in bt:
        return f"[^{content}]"

    # Page headers/footers — skip (redundant)
    if "pageheader" in bt or "pagefooter" in bt:
        return ""

    # Default: plain text paragraph
    if content.strip():
        return content.strip()

    return ""


def _verified_parse_sync(file_path: str, pdf_hash: str = "") -> dict:
    """深度解析：Marker（默认）。MinerU 作为可选备用（需联网下载 VLM 模型）。"""
    try:
        return _marker_parse_sync(file_path, pdf_hash)
    except Exception as e:
        raise RuntimeError(f"Marker parse failed: {e}")


class DocumentParser:
    def parse(self, file_path: str) -> dict:
        pdf_hash = sha256_file(Path(file_path))
        quick_cache = CACHE_DIR / f"{pdf_hash}.quick.json"
        verified_cache = CACHE_DIR / f"{pdf_hash}.verified.json"

        # Check cache
        if verified_cache.exists():
            with open(verified_cache, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["quality"] = "verified"
            data["status"] = "available"
            return data
        if quick_cache.exists():
            with open(quick_cache, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["quality"] = "quick"
            data["status"] = "available"
            self._start_verified_background(file_path, pdf_hash)
            return data

        # Quick parse
        quick = pymupdf_parse(file_path)
        quick["hash"] = pdf_hash
        quick["quality"] = "quick"
        quick["status"] = "available"
        with open(quick_cache, "w", encoding="utf-8") as f:
            json.dump(quick, f, ensure_ascii=False, indent=2)

        # Background start Verified
        self._start_verified_background(file_path, pdf_hash)
        return quick

    def _start_verified_background(self, file_path: str, pdf_hash: str):
        """Start background verified parsing in a daemon thread (no executor — more robust)."""
        t = threading.Thread(
            target=self._verified_background,
            args=(file_path, pdf_hash),
            daemon=True,
        )
        t.start()

    def _verified_background(self, file_path: str, pdf_hash: str):
        """Background verified parsing with user_modified protection."""
        try:
            print(f"[Verified] Starting Marker parse for {pdf_hash[:12]}...")
            result = _verified_parse_sync(file_path, pdf_hash)
            result["hash"] = pdf_hash
            result["quality"] = "verified"
            result["status"] = "available"
            verified_cache = CACHE_DIR / f"{pdf_hash}.verified.json"

            # Check user_modified before overwriting
            try:
                from data.db import PaperDB
                db = PaperDB()
                try:
                    paper = db.get_paper_by_hash(pdf_hash)
                    if paper and paper.get("user_modified"):
                        print(f"[Verified] {pdf_hash[:12]} skipped: user_modified=True")
                        return
                finally:
                    db.close()
            except Exception:
                pass

            with open(verified_cache, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            # Update DB status + re-extract metadata from cleaner text
            try:
                from data.db import PaperDB
                import re
                db = PaperDB()
                try:
                    # Re-extract metadata from verified (cleaner) text
                    vtext = result.get("full_text", "")[:3000]
                    better_title = ""
                    better_author = ""
                    lines = [l.strip() for l in vtext.split("\n") if l.strip()]
                    if lines:
                        better_title = lines[0][:300]
                        if len(lines) > 1 and len(lines[1]) < 200:
                            better_author = lines[1][:500]

                    db.conn.execute(
                        "UPDATE papers SET parse_status='verified', parsed_verified_path=?, "
                        "title=CASE WHEN title='' OR title IS NULL THEN ? ELSE title END, "
                        "authors=CASE WHEN authors='' OR authors IS NULL THEN ? ELSE authors END "
                        "WHERE paper_hash=?",
                        (str(verified_cache), better_title, better_author, pdf_hash)
                    )
                    db.conn.commit()
                finally:
                    db.close()
            except Exception:
                pass

            # Re-index ChromaDB with verified (smarter) text
            try:
                from core.rag import reindex_paper
                from data.db import PaperDB
                db2 = PaperDB()
                try:
                    p = db2.get_paper_by_hash(pdf_hash)
                    if p:
                        pages = result.get("pages", [])
                        n = reindex_paper(p["id"], pages)
                        print(f"[Verified] {pdf_hash[:12]} reindexed {n} chunks into ChromaDB")
                finally:
                    db2.close()
            except Exception as e:
                print(f"[Verified] {pdf_hash[:12]} reindex failed: {e}")

            print(f"[Verified] {pdf_hash[:12]} done ({len(result.get('full_text',''))} chars)")
        except Exception as e:
            print(f"[Verified] {pdf_hash[:12]} failed: {e}")
