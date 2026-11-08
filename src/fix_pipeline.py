import ast

from src.check_generator import generate_checks, run_checks
from src.fixer import FIX_PROMPT, clean_code
from src.llm_client import ask_llm
from src.program_runner import missing_message, missing_modules
from src.security_scanner import scan_security
from src.static_analyzer import pylint_errors

RETRY_PROMPT = """You are a Python expert.
Your previous fix did not work.
Make the smallest possible change. Do not add new features, new imports or platform-specific paths.
Never make a function return a constant, and never remove what it does, just to pass the checks.
Never keep hardcoded secrets, never use shell=True or eval, and never build SQL from user input.
The user's requirement (follow it if it is given): {requirement}
Reply with ONLY the complete fixed Python code. No explanation, no markdown fences.

Problems to fix:
{problems}

Original code:
{original}

Your previous fix:
{previous}

What went wrong:
{feedback}
"""

SERIOUS = ("HIGH", "MEDIUM")
SHELL_BUILTINS = {"echo", "dir", "cd", "copy", "type", "del", "cls", "ver", "move", "ren"}
SUBPROCESS_CALLS = {"run", "call", "Popen", "check_call", "check_output"}


def _is_stub(func):
    body = list(func.body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    if not body:
        return True
    for stmt in body:
        if isinstance(stmt, (ast.Pass, ast.Raise)):
            continue
        if isinstance(stmt, ast.Return) and (
                stmt.value is None or isinstance(stmt.value, ast.Constant)):
            continue
        return False
    return True


def gutted(original, fixed):
    """Names of functions the fix removed or reduced to a stub."""
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef)
    try:
        old = {n.name: n for n in ast.walk(ast.parse(original)) if isinstance(n, kinds)}
        new = {n.name: n for n in ast.walk(ast.parse(fixed)) if isinstance(n, kinds)}
    except SyntaxError:
        return []
    bad = []
    for name, func in old.items():
        if _is_stub(func):
            continue
        if name not in new or _is_stub(new[name]):
            bad.append(name)
    return bad


def builtin_feedback(code):
    """Flags subprocess calls that start a shell built-in as if it were a program."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in SUBPROCESS_CALLS or not node.args:
            continue
        first = node.args[0]
        if (isinstance(first, (ast.List, ast.Tuple)) and first.elts
                and isinstance(first.elts[0], ast.Constant)
                and first.elts[0].value in SHELL_BUILTINS):
            found.append(f"line {node.lineno}: {first.elts[0].value}")
    if not found:
        return ""
    return ("Shell built-ins are not programs on Windows and will fail there ("
            + ", ".join(found)
            + "). Use Python instead, for example print(), os, shutil or pathlib.")


def serious_issues(issues):
    return [i for i in issues
            if str(i.get("severity", "")).upper() in SERIOUS and i.get("id") != "error"]


def bug_lines(bugs):
    return [f"- Line {b.get('line')}: {b.get('explanation')}"
            for b in bugs if b.get("type") != "parse_error"]


def confirmed_lines(bugs):
    return [f"- Line {b.get('line')}: {b.get('explanation')}"
            for b in bugs if b.get("confirmed")]


def security_lines(issues):
    return [f"- Line {i.get('line')}: {i.get('issue')}" for i in serious_issues(issues)]


def pylint_feedback(code):
    try:
        errors = pylint_errors(code)
    except Exception:
        return ""
    if not errors:
        return ""
    return "pylint reports errors:\n" + "\n".join(
        f"line {e['line']}: {e['issue']}" for e in errors)


def remaining_findings(code):
    try:
        found = scan_security(code)
    except Exception:
        return []
    return [{"line": i.get("line"), "id": i.get("id"),
             "severity": str(i.get("severity", "")).upper(),
             "issue": i.get("issue")}
            for i in found if i.get("id") != "error"]


def fix_and_verify(code, bugs, issues, description="", provider=None, max_tries=3):
    result = {"fixed_code": None, "syntax_check": "", "verified": None,
              "verify_message": "", "tries": 0, "checks": [], "remaining": [],
              "missing_modules": [], "no_action": False, "error": None}
    description = (description or "").strip()
    requirement = description or "none given"
    confirmed = confirmed_lines(bugs)
    serious = security_lines(issues)
    original_has_builtin = bool(builtin_feedback(code))
    missing = missing_modules(code)

    checks = None
    problems = None
    if missing:
        result["missing_modules"] = missing
        result["verify_message"] = missing_message(missing)
    elif description:
        checks = generate_checks(code, description, provider=provider)
        if checks:
            result["checks"] = checks
            before = run_checks(code, checks)
            if before["passed"]:
                if not confirmed and not serious:
                    result.update(fixed_code=code, syntax_check="syntax OK",
                                  verified=True, no_action=True,
                                  verify_message="your code already passes all checks")
                    return result
                problems = "\n".join(confirmed + serious)
            else:
                parts = bug_lines(bugs) + serious
                parts.append("- The code fails these checks:\n" + before["message"])
                problems = "\n".join(parts)
        else:
            result["verify_message"] = "could not generate checks"
    else:
        result["verify_message"] = "no description given"

    if problems is None:
        problems = "\n".join(bug_lines(bugs) + serious)
    if not problems:
        result["error"] = "nothing to fix"
        return result

    prompt = FIX_PROMPT.format(problems=problems, code=code, requirement=requirement)
    feedback = ""
    for attempt in range(1, max_tries + 1):
        fixed = clean_code(ask_llm(prompt, provider=provider))
        result["tries"] = attempt
        result["fixed_code"] = fixed
        try:
            ast.parse(fixed)
            result["syntax_check"] = "syntax OK"
        except SyntaxError as e:
            result["syntax_check"] = "syntax error: " + str(e)
            result["remaining"] = []
            feedback = result["syntax_check"]
        else:
            result["remaining"] = remaining_findings(fixed)
            serious_left = [r for r in result["remaining"] if r["severity"] in SERIOUS]
            removed = gutted(code, fixed)
            builtin = "" if original_has_builtin else builtin_feedback(fixed)
            lint = pylint_feedback(fixed)
            if removed:
                feedback = ("The fix removed or stubbed out what these functions do: "
                            + ", ".join(removed)
                            + ". Keep their behavior and fix only the listed problems.")
            elif builtin:
                feedback = builtin
            elif lint:
                feedback = lint
            elif serious_left:
                feedback = "Bandit still reports serious issues:\n" + "\n".join(
                    f"line {r['line']}: {r['issue']}" for r in serious_left)
            else:
                feedback = ""
            if not feedback:
                if not checks:
                    return result
                outcome = run_checks(fixed, checks)
                if outcome["passed"]:
                    result["verified"] = True
                    result["verify_message"] = "all checks passed"
                    return result
                feedback = outcome["message"]
        prompt = RETRY_PROMPT.format(
            problems=problems, original=code, previous=fixed,
            feedback=feedback, requirement=requirement)

    if checks or feedback.startswith(
            ("pylint", "The fix removed", "Bandit still", "Shell built-in")):
        result["verified"] = False
        result["verify_message"] = feedback
    return result
