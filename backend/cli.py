"""DeepRead CLI — 终端直接对话模式.

Usage:  python cli.py
        python cli.py --paper 1    (直接指定论文ID)
        python cli.py --list       (列出所有论文)
"""

import sys
import json
import asyncio
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND_DIR))

from data.db import PaperDB
from agent.loop import run_react_loop_streaming
from config import get_profile_config
from dotenv import load_dotenv

load_dotenv(_BACKEND_DIR.parent / ".env")

# ── Terminal colors ──
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_CYAN = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE = "\033[34m"
C_RED = "\033[31m"
C_MAGENTA = "\033[35m"


def print_banner():
    print(f"{C_CYAN}{C_BOLD}")
    print("+======================================+")
    print("|       DeepRead CLI Chat           |")
    print("|   本地文献阅读智能工作站 · 终端对话  |")
    print("+======================================+")
    print(f"{C_RESET}")


def list_papers():
    db = PaperDB()
    try:
        papers = db.list_papers()
        if not papers:
            print(f"{C_YELLOW}No papers in database. Upload a PDF first.{C_RESET}")
            return None
        print(f"\n{C_BOLD}Available papers:{C_RESET}")
        for i, p in enumerate(papers):
            title = (p.get("title") or f"Paper #{p['id']}")[:70]
            status = p.get("parse_status", "?")
            status_icon = {"verified": "V", "quick": "o", "parsing_verified": ">"}.get(status, "?")
            print(f"  {C_GREEN}[{i+1}]{C_RESET}  {status_icon} {title}")
        return papers
    finally:
        db.close()


def select_paper(papers, cli_arg=None):
    if cli_arg is not None:
        try:
            pid = int(cli_arg)
            if pid == 0:
                return None  # No-paper mode
            for p in papers:
                if p["id"] == pid:
                    return p
        except ValueError:
            pass

    while True:
        try:
            if papers:
                print(f"\n{C_BOLD}Select paper (1-{len(papers)}, 0=no paper): {C_RESET}", end="")
            else:
                print(f"\n{C_BOLD}No papers in library. Enter 0 to start anyway: {C_RESET}", end="")
            choice = input().strip()
            if choice in ("q", "quit", "exit"):
                return None
            if choice == "0":
                return None  # No-paper mode
            if papers:
                idx = int(choice) - 1
                if 0 <= idx < len(papers):
                    return papers[idx]
            print(f"{C_RED}Invalid choice.{C_RESET}")
        except (ValueError, KeyboardInterrupt):
            print()
            return None


async def run_chat(paper, conv_id=0):
    if paper:
        paper_id = paper["id"]
        title = (paper.get("title") or f"Paper #{paper_id}")[:60]
        print(f"\n{C_BOLD}Reading:{C_RESET} {C_CYAN}{title}{C_RESET}")
        cli_hint = ""
    else:
        paper_id = 0
        print(f"\n{C_BOLD}Mode:{C_RESET} {C_YELLOW}No-paper (search / skill / run / general chat){C_RESET}")
        cli_hint = (
            "\nYou are in CLI terminal mode. Use tools for everything — do NOT just output text. "
            "For papers: read(query,paper_id) / search(query,scope) / compare(paper_ids,dimension). "
            "For code: run(code='...') with Python. "
            "stdlib + matplotlib/numpy/PIL/pandas are available. "
            "Files save to cwd (storage/workspace/), use just the filename."
        )

    profile = get_profile_config()
    print(f"{C_DIM}Type /help for commands, /exit to quit{C_RESET}\n")

    while True:
        try:
            question = input(f"{C_GREEN}{C_BOLD}You:{C_RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not question:
            continue

        # Handle commands
        if question.startswith("/"):
            cmd = question.lower()
            if cmd in ("/exit", "/quit", "/q"):
                break
            elif cmd == "/help":
                print(f"  {C_BOLD}Commands:{C_RESET}")
                print(f"  /exit, /quit, /q  - Exit chat")
                print(f"  /papers           - Switch paper")
                print(f"  /verbose, /v      - Toggle verbose (show full observations)")
                print(f"  /clear, /c        - Start new conversation")
                print()
                continue
            elif cmd == "/papers":
                papers = list_papers()
                if papers:
                    p = select_paper(papers)
                    if p:
                        paper = p
                        paper_id = p["id"]
                        conv_id = 0
                        cli_hint = ""
                        title = (p.get("title") or f"Paper #{paper_id}")[:60]
                        print(f"{C_BOLD}Switched to:{C_RESET} {C_CYAN}{title}{C_RESET}")
                continue
            elif cmd in ("/clear", "/c"):
                conv_id = 0
                print(f"{C_GREEN}Started new conversation.{C_RESET}")
                continue
            elif cmd in ("/verbose", "/v"):
                global VERBOSE
                VERBOSE = not VERBOSE
                print(f"{C_GREEN}Verbose: {VERBOSE}{C_RESET}")
                continue
            else:
                print(f"{C_RED}Unknown command: {question}{C_RESET}")
                continue

        # Inject CLI mode hint into question
        if cli_hint:
            question = cli_hint + "\n\nQuestion: " + question

        # ── Run agent ──
        print()
        step = 0
        full_answer = ""
        try:
            async for event in run_react_loop_streaming(
                paper_id=paper_id,
                conv_id=conv_id,
                question=question,
                provider="deepseek",
                user_field=profile.get("field", ""),
                user_level=profile.get("level", ""),
                user_language=profile.get("language", "Chinese"),
            ):
                etype = event.get("event", "")
                data = event.get("data", "")

                if etype == "status":
                    status_text = data if isinstance(data, str) else str(data)
                    # Skip verbose status messages, only show key ones
                    if "Reading:" in status_text:
                        pass  # already shown
                    elif "Compacting" in status_text:
                        print(f"  {C_YELLOW}> {status_text}{C_RESET}")
                    elif "Thinking" in status_text:
                        print(f"  {C_DIM}{status_text}{C_RESET}")

                elif etype == "tool_call":
                    step += 1
                    tool = data.get("tool", "?") if isinstance(data, dict) else "?"
                    params = data.get("params", {}) if isinstance(data, dict) else {}
                    params_str = json.dumps(params, ensure_ascii=False)
                    if len(params_str) > 80:
                        params_str = params_str[:80] + "..."
                    print(f"  {C_BLUE}[Step {step}]{C_RESET} {C_BOLD}{tool}{C_RESET}({C_DIM}{params_str}{C_RESET})")

                elif etype == "observation":
                    if VERBOSE:
                        obs = data if isinstance(data, str) else str(data)
                        # Show first 300 chars of observation
                        lines = obs.strip().split("\n")
                        preview = lines[0][:200] if lines else obs[:200]
                        print(f"  {C_DIM}  <- {preview}...{C_RESET}")

                elif etype == "content":
                    token = data.get("token", "") if isinstance(data, dict) else str(data)
                    if token and not token.startswith("\n\n"):
                        print(token, end="", flush=True)
                    full_answer += token

                elif etype == "done":
                    d = data if isinstance(data, dict) else {}
                    cancelled = d.get("cancelled", False)
                    if cancelled:
                        print(f"\n  {C_YELLOW}@ Cancelled{C_RESET}")
                    conv_id = d.get("conv_id", conv_id)
                    print()  # newline after streaming

        except Exception as e:
            print(f"\n  {C_RED}Error: {e}{C_RESET}")

        print()  # blank line between Q&A


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="DeepRead CLI Chat")
    parser.add_argument("--paper", type=int, help="Paper ID to start with")
    parser.add_argument("--list", action="store_true", help="List papers and exit")
    args = parser.parse_args()

    print_banner()

    papers = list_papers()
    if not papers:
        return

    if args.list:
        return

    paper = select_paper(papers, cli_arg=args.paper)
    if paper is None and args.paper is not None and args.paper != 0:
        return  # User explicitly chose to quit

    # Warm up embedder in background
    import threading
    def warmup():
        try:
            from core.embedder import get_model
            print(f"{C_DIM}Warming up embedding model...{C_RESET}")
            get_model()
        except Exception:
            pass
    threading.Thread(target=warmup, daemon=True).start()

    await run_chat(paper)


VERBOSE = False

if __name__ == "__main__":
    asyncio.run(main())
