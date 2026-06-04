"""Tool: execute Python code via subprocess with blacklist sandbox."""

import subprocess
import tempfile
import os
import re
from pathlib import Path

_WORKSPACE = Path(__file__).resolve().parent.parent.parent / "storage" / "workspace"
_workspace_str = str(_WORKSPACE).replace("\\", "/")

# Patterns forbidden in user code (regex match on code text)
FORBIDDEN = [
    r"os\.system", r"os\.popen", r"subprocess",
    r"__import__\(", r"eval\(", r"exec\(",
    r"shutil\.rmtree", r"os\.remove", r"os\.unlink",
    r"open\(['\"].*\.\.",     # prevent "../" path traversal in open()
]

# Modules blocked at import level (truly dangerous or sandbox-escaping)
BLOCKED = {
    "subprocess", "shutil", "ctypes", "importlib",
    "code", "pdb", "inspect", "traceback", "sysconfig",
    "socket", "socketserver", "asyncio",
}

MAX_OUTPUT = 5000
TIMEOUT = 30  # Give matplotlib time to render


def execute(code: str) -> str:
    # Security scan
    for pattern in FORBIDDEN:
        if re.search(pattern, code, re.MULTILINE):
            return f"[run] Forbidden pattern: {pattern}"

    # Build sandboxed script with blacklist import guard
    blocked_set = repr(BLOCKED)
    sandbox = f"""
import builtins
_orig = builtins.__import__
_blocked = {blocked_set}
def _safe_import(name, *a, **kw):
    root = name.split('.')[0]
    if root in _blocked:
        raise ImportError(f"Blocked import: {{name}} ({{root}} is not allowed)")
    return _orig(name, *a, **kw)
builtins.__import__ = _safe_import

""" + code

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    )
    tmp.write(sandbox)
    tmp.close()

    try:
        result = subprocess.run(
            ["python", tmp.name],
            capture_output=True, text=True, timeout=TIMEOUT,
            cwd=_workspace_str,
            env={**os.environ, "HOME": _workspace_str, "MPLBACKEND": "Agg"},
        )
        output = (result.stdout or "") + (result.stderr or "")
        return f"[run]\n{output[:MAX_OUTPUT]}"
    except subprocess.TimeoutExpired:
        return "[run] Timeout (30s)"
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
