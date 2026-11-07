import json
import os
import subprocess
import sys
import tempfile


def scan_security(code):
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "target.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        result = subprocess.run(
            [sys.executable, "-m", "bandit", "-f", "json", path],
            capture_output=True,
            text=True,
            timeout=60,
        )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [{"line": None, "id": "error", "severity": "?", "issue": result.stderr[:200]}]
    return [
        {
            "line": r["line_number"],
            "id": r["test_id"],
            "severity": r["issue_severity"],
            "issue": r["issue_text"],
        }
        for r in data.get("results", [])
    ]