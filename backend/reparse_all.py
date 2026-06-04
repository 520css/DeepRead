"""Re-parse all quick-only papers with Marker (verified parse)."""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.parser import _marker_parse_sync
from data.db import PaperDB

PARSED_DIR = Path(__file__).resolve().parent.parent / "storage" / "parsed"
db = PaperDB()
papers = db.list_papers()

for p in papers:
    pid = p["id"]
    title = (p.get("title") or "?")[:50]

    verified_path = p.get("parsed_verified_path", "")
    if verified_path and Path(verified_path).exists():
        print(f"[{pid}] {title} - already verified, skip")
        continue

    pdf_path = p.get("file_path", "")
    if not pdf_path or not Path(pdf_path).exists():
        print(f"[{pid}] {title} - PDF missing, skip")
        continue

    pdf_hash = p.get("paper_hash", "")
    print(f"[{pid}] {title} - parsing...")
    try:
        result = _marker_parse_sync(pdf_path, pdf_hash)
        out_path = PARSED_DIR / f"{pdf_hash}.verified.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        db.update_parse_status(pid, "verified", verified_path=str(out_path))
        print(f"  -> OK ({len(result.get('full_text', ''))} chars)")
    except Exception as e:
        print(f"  -> FAILED: {e}")

db.close()
print("Done.")
