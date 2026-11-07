import json
import os
import subprocess
import sys
import tempfile

from src.llm_client import ask_llm

FENCE = "`" * 3

CHECK_PROMPT = """You write test checks for Python code.
The user says the code should do this:
{description}

Code:
{code}

Write 3 to 5 small checks that test what the user described.
Reply ONLY with a JSON list. No extra text.
Each item must have: "call" (a Python expression that calls a function from the code) and "expected" (a Python expression for the correct result).
Use only simple literal values. Do not call input() or print().
Example: [{{"call": "add_tax(100)", "expected": "110"}}]
"""

RUNNER = '''
import ast, json, sys
code = open(sys.argv[1], encoding="utf-8").read()
checks = json.load(open(sys.argv[2], encoding="utf-8"))
ns = {"__name__": "checked_code"}
try:
    tree = ast.parse(code)
    keep = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            keep.append(node)
        elif isinstance(node, ast.Assign):
            try:
                ast.literal_eval(node.value)
                keep.append(node)
            except Exception:
                pass
    tree.body = keep
    exec(compile(tree, "target", "exec"), ns)
except BaseException as e:
    print(json.dumps({"load_error": repr(e)}))
    sys.exit(0)
results = []
for c in checks:
    try:
        actual = eval(c["call"], ns)
        expected = eval(c["expected"], {})
        results.append({"call": c["call"], "expected": repr(expected),
                        "actual": repr(actual), "passed": actual == expected})
    except BaseException as e:
        results.append({"call": c["call"], "expected": c["expected"],
                        "actual": "error: " + repr(e), "passed": False})
print(json.dumps({"results": results}))
'''


def generate_checks(code, description, provider=None):
    prompt = CHECK_PROMPT.format(description=description, code=code)
    reply = ask_llm(prompt, provider=provider).strip()
    reply = reply.removeprefix(FENCE + "json").removeprefix(FENCE).removesuffix(FENCE).strip()
    try:
        items = json.loads(reply)
    except json.JSONDecodeError:
        return []
    checks = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("call"), str) and "expected" in it:
                checks.append({"call": it["call"], "expected": str(it["expected"])})
    return checks


def run_checks(code, checks, timeout=30):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        paths = {n: os.path.join(tmp, n) for n in ("target.py", "checks.json", "runner.py")}
        with open(paths["target.py"], "w", encoding="utf-8") as f:
            f.write(code)
        with open(paths["checks.json"], "w", encoding="utf-8") as f:
            json.dump(checks, f)
        with open(paths["runner.py"], "w", encoding="utf-8") as f:
            f.write(RUNNER)
        try:
            result = subprocess.run(
                [sys.executable, paths["runner.py"], paths["target.py"], paths["checks.json"]],
                cwd=tmp, capture_output=True, text=True, encoding="utf-8",
                errors="replace", stdin=subprocess.DEVNULL, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"passed": False, "results": [],
                    "message": f"timeout after {timeout}s (possible infinite loop)"}

    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"passed": False, "results": [],
                "message": "could not run checks: " + result.stderr[-300:]}
    if "load_error" in data:
        return {"passed": False, "results": [],
                "message": "code failed to load: " + data["load_error"]}

    results = data["results"]
    failed = [r for r in results if not r["passed"]]
    if failed:
        lines = [f"{r['call']} returned {r['actual']}, expected {r['expected']}" for r in failed]
        return {"passed": False, "results": results, "message": "\n".join(lines)}
    if not results:
        return {"passed": False, "results": [], "message": "no checks to run"}
    return {"passed": True, "results": results, "message": "all checks passed"}


def make_checks(code, description, provider=None):
    checks = generate_checks(code, description, provider=provider)
    if not checks:
        return None, "could not generate checks"
    before = run_checks(code, checks)
    if before["passed"]:
        return None, "checks do not catch the bug (they pass on the original code)"
    return checks, "ok"