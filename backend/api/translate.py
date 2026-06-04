"""API route for translating selected text using DeepSeek with academic terminology preservation."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path

router = APIRouter(prefix="/api/translate", tags=["translate"])

_ROOT = Path(__file__).resolve().parent.parent.parent  # paperbridge/
SKILLS_DIR = _ROOT / "skills"


class TranslateRequest(BaseModel):
    text: str


def _load_translate_prompt() -> str:
    """Load translation prompt template from skills/translate.md."""
    skill_file = SKILLS_DIR / "translate.md"
    if not skill_file.exists():
        return "Translate the following academic text into Chinese. Preserve technical terms in English with Chinese in parentheses.\n\n{content}"

    text = skill_file.read_text(encoding="utf-8")
    # Extract content after YAML frontmatter (--- ... ---)
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text.strip()


@router.post("")
async def translate_text(body: TranslateRequest):
    """Translate selected text to Chinese using DeepSeek."""
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="No text provided")

    from core.llm_router import router as llm_router

    prompt_template = _load_translate_prompt()
    prompt = prompt_template.replace("{content}", body.text.strip())

    try:
        result = await llm_router.complete_single(
            messages=[{"role": "user", "content": prompt}],
            task_type="translation",
            max_tokens=2048,
        )
        return {"translation": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Translation failed: {str(e)}")
