"""API routes for cost dashboard and usage statistics."""

from fastapi import APIRouter
from data.db import PaperDB
from config import get_budget_config

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/usage")
async def usage_stats():
    """Get LLM usage statistics: monthly cost, by provider, by task type."""
    db = PaperDB()
    try:
        budget_cfg = get_budget_config()
        monthly_limit = budget_cfg.get("monthly_limit_usd", 20.0)

        # Monthly total
        total_row = db.conn.execute(
            """SELECT COALESCE(SUM(cost_usd), 0) as total,
                      COALESCE(SUM(input_tokens), 0) as inp,
                      COALESCE(SUM(output_tokens), 0) as out
               FROM llm_usage
               WHERE strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now')"""
        ).fetchone()

        # By provider
        by_provider = db.conn.execute(
            """SELECT provider,
                      COALESCE(SUM(cost_usd), 0) as cost,
                      SUM(input_tokens) as inp,
                      SUM(output_tokens) as out,
                      COUNT(*) as calls
               FROM llm_usage
               WHERE strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now')
               GROUP BY provider"""
        ).fetchall()

        # By task type
        by_task = db.conn.execute(
            """SELECT task_type,
                      COALESCE(SUM(cost_usd), 0) as cost,
                      COUNT(*) as calls
               FROM llm_usage
               WHERE strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now')
               GROUP BY task_type"""
        ).fetchall()

        # Paper count
        paper_count = db.conn.execute("SELECT COUNT(*) as cnt FROM papers").fetchone()

        # Conversation count
        conv_count = db.conn.execute("SELECT COUNT(*) as cnt FROM conversations").fetchone()

        total = dict(total_row) if total_row else {"total": 0, "inp": 0, "out": 0}

        return {
            "monthly": {
                "cost_usd": round(total.get("total", 0), 4),
                "input_tokens": total.get("inp", 0),
                "output_tokens": total.get("out", 0),
                "limit_usd": monthly_limit,
                "usage_pct": round(total.get("total", 0) / monthly_limit * 100, 1) if monthly_limit else 0,
                "status": "warning" if total.get("total", 0) >= monthly_limit * 0.8 else "ok",
            },
            "by_provider": [dict(r) for r in by_provider],
            "by_task": [dict(r) for r in by_task],
            "totals": {
                "papers": paper_count["cnt"] if paper_count else 0,
                "conversations": conv_count["cnt"] if conv_count else 0,
            },
        }
    finally:
        db.close()


@router.get("/budget")
async def budget_status():
    """Get current budget status."""
    db = PaperDB()
    try:
        budget_cfg = get_budget_config()
        monthly_limit = budget_cfg.get("monthly_limit_usd", 20.0)
        warn_threshold = budget_cfg.get("warn_threshold", 0.8)
        on_exceed = budget_cfg.get("on_exceed", "downgrade")

        current = db.get_monthly_cost()

        return {
            "limit_usd": monthly_limit,
            "current_usd": round(current, 4),
            "remaining_usd": round(monthly_limit - current, 4),
            "usage_pct": round(current / monthly_limit * 100, 1) if monthly_limit else 0,
            "warn_threshold_pct": warn_threshold * 100,
            "on_exceed": on_exceed,
            "warning": current >= monthly_limit * warn_threshold,
            "exceeded": current >= monthly_limit,
        }
    finally:
        db.close()
