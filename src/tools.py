import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Characters kept per stream before a truncation notice is appended.
MAX_OUTPUT_CHARS = 8_000


def _truncate(text: str, label: str) -> str:
    """Return *text* trimmed to MAX_OUTPUT_CHARS with a clear notice if cut."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    kept = text[:MAX_OUTPUT_CHARS]
    dropped = len(text) - MAX_OUTPUT_CHARS
    return f"{kept}\n[{label} truncated — {dropped} additional characters not shown]"


def call_tool(args: dict) -> dict:
    command = args["command"]
    timeout = args.get("timeout", 30)

    try:
        result = subprocess.run(
            ["bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=PROJECT_ROOT,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "exit_code": None,
            "stdout": _truncate(exc.stdout or "", "stdout"),
            "stderr": _truncate(exc.stderr or "", "stderr"),
            "error": f"Command, {command}, timed out after {timeout} seconds.",
        }

    return {
        "command": command,
        "exit_code": result.returncode,
        "stdout": _truncate(result.stdout, "stdout"),
        "stderr": _truncate(result.stderr, "stderr"),
    }
