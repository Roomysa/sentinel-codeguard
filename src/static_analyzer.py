import json
import os
import re
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


def pylint_errors_project(files):
    """files: {name: code}. Lints every file together so that local imports
    resolve. Returns confirmed crash errors, each with a 'file' key."""
    local = {n[:-3] for n in files if n.endswith(".py")}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        paths = []
        for name, text in files.items():
            path = os.path.join(folder, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            paths.append(path)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pylint", "--disable=all", "--enable=E,F",
                 "--output-format=json", *paths],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=90, cwd=folder,
            )
        except subprocess.TimeoutExpired:
            return []
    if "No module named" in result.stderr:
        raise RuntimeError("pylint is not installed")
    try:
        items = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []

    errors = []
    for m in items:
        symbol = m.get("symbol")
        keep = symbol in KEEP
        if symbol == "no-name-in-module":
            found = re.search(r"in module '([^']+)'", m.get("message", ""))
            keep = bool(found) and found.group(1).split(".")[0] in local
        if keep:
            errors.append({
                "file": os.path.basename(m.get("path", "")),
                "line": int(m.get("line") or 0),
                "id": m.get("message-id", ""),
                "symbol": symbol,
                "issue": m.get("message", ""),
            })
    return errors
