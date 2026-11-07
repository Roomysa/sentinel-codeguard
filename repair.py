import ast

from src.bug_finder import find_bugs
from src.fixer import FIX_PROMPT, clean_code
from src.llm_client import ask_llm
from src.verifier import verify_fix

RETRY_PROMPT = """You are a Python expert.
Your previous fix did not pass the tests.
Reply with ONLY the complete fixed Python code. No explanation, no markdown fences.

Original buggy code:
{original}

Your previous fix:
{previous}

Test result:
{feedback}
"""


def problems_text(bugs):
    lines = []
    for b in bugs:
        if b.get("type") != "parse_error":
            lines.append(f"- Line {b.get('line')}: {b.get('explanation')}")
    return "\n".join(lines)


def repair(program, code, provider=None, max_tries=3):
    found = find_bugs(code, provider=provider)
    bugs = [b for b in found if isinstance(b, dict)] if isinstance(found, list) else []
    problems = problems_text(bugs)
    found_by = "AI review"

    if not problems:
        # AI saw no bug: let the tests decide
        passed, feedback = verify_fix(program, code)
        if passed:
            return {"passed": False, "tries": 0,
                    "note": "AI found no bugs and the tests already pass"}
        problems = "- The code fails its tests:\n" + feedback
        found_by = "tests"

    prompt = FIX_PROMPT.format(problems=problems, code=code, requirement="none given")
    note = ""
    for attempt in range(1, max_tries + 1):
        fixed = clean_code(ask_llm(prompt, provider=provider))
        try:
            ast.parse(fixed)
        except SyntaxError as e:
            passed, feedback = False, "syntax error: " + str(e)
        else:
            passed, feedback = verify_fix(program, fixed)
        if passed:
            return {"passed": True, "tries": attempt,
                    "note": found_by + ": " + feedback, "code": fixed}
        note = feedback
        prompt = RETRY_PROMPT.format(original=code, previous=fixed, feedback=feedback)
    return {"passed": False, "tries": max_tries, "note": found_by + ": " + note}