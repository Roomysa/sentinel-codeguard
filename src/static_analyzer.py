import json
import os
import subprocess
import sys
import tempfile

# Only crash-type errors that pylint is reliably right about
KEEP = {
    "undefined-variable",
    "used-before-assignment",
    "no-value-for-parameter",
    "too-many-function-args",
    "unexpected-keyword-arg",
    "not-callable",
    "return-outside-function",
    "syntax-error",
}


def _run_pylint(code, enable):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        path = os.path.join(folder, "target.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pylint", "--disable=all",
                 "--enable=" + enable, "--output-format=json", path],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60,
            )
        except subprocess.TimeoutExpired:
            return []
    if "No module named" in result.stderr:
        raise RuntimeError("pylint is not installed")
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []


def pylint_hints(code):
    items = _run_pylint(code, "E,F")
    lines = [f"- Line {m['line']}: {m['message']}" for m in items]
    if not lines:
        return ""
    return (
        "\nStatic analysis hints (may be wrong, verify them):\n"
        + "\n".join(lines)
        + "\n"
    )


def pylint_errors(code):
    errors = []
    for m in _run_pylint(code, "E,F"):
        if m.get("symbol") in KEEP:
            errors.append({
                "line": int(m.get("line") or 0),
                "id": m.get("message-id", ""),
                "symbol": m.get("symbol", ""),
                "issue": m.get("message", ""),
            })
    return errors