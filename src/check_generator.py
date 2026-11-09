import json

from src import sandbox
from src.llm_client import ask_llm

FENCE = "`" * 3

CHECK_PROMPT = """You write test checks for Python code.
The user says the code should do this:
{description}

Code:
{code}
{context}
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


def generate_checks(code, description, provider=None, context=""):
    prompt = CHECK_PROMPT.format(description=description, code=code, context=context)
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


def run_checks(code, checks, timeout=30, extra_files=None):
    files = dict(extra_files or {})
    files.update({"target.py": code, "checks.json": json.dumps(checks),
                  "runner.py": RUNNER})
    out = sandbox.run_script(files, "runner.py", ["target.py", "checks.json"],
                             timeout=timeout)
    box = out["sandboxed"]

    if out["timed_out"]:
        return {"passed": False, "results": [], "sandboxed": box,
                "message": f"timeout after {timeout}s (possible infinite loop)"}
    try:
        data = json.loads(out["stdout"].strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"passed": False, "results": [], "sandboxed": box,
                "message": "could not run checks: " + out["stderr"][-300:]}
    if "load_error" in data:
        return {"passed": False, "results": [], "sandboxed": box,
                "message": "code failed to load: " + data["load_error"]}

    results = data["results"]
    failed = [r for r in results if not r["passed"]]
    if failed:
        lines = [f"{r['call']} returned {r['actual']}, expected {r['expected']}" for r in failed]
        return {"passed": False, "results": results, "sandboxed": box,
                "message": "\n".join(lines)}
    if not results:
        return {"passed": False, "results": [], "sandboxed": box,
                "message": "no checks to run"}
    return {"passed": True, "results": results, "sandboxed": box,
            "message": "all checks passed"}


def make_checks(code, description, provider=None):
    checks = generate_checks(code, description, provider=provider)
    if not checks:
        return None, "could not generate checks"
    before = run_checks(code, checks)
    if before["passed"]:
        return None, "checks do not catch the bug (they pass on the original code)"
    return checks, "ok"
