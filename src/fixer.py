import ast

from src.llm_client import ask_llm

FIX_PROMPT = """You are a careful Python security and bug-fixing expert.
Fix ONLY the problems listed below in the code.

Rules:
- Make the smallest possible change that fixes each listed problem.
- Keep the existing behavior, function names and signatures unchanged.
- Never remove or stub out what a function does, and never make it return a constant just to pass tests.
- Do not add new features, extra error handling or fake classes that were not in the original. Add an import only if the fix needs it.
- Do not use hardcoded absolute paths or anything that works only on one operating system.
- The code must run on Windows, Linux and macOS. Do not call shell built-ins such as echo, dir, cd, copy or type as programs; use Python equivalents (print, os, shutil, pathlib).
- Never leave hardcoded passwords, keys or tokens in the code. Read them with os.getenv("NAME") or take them as an argument.
- Build SQL queries with placeholders and pass the values separately. Never join user input into a query string.
- Never use shell=True, os.system, eval() or pickle.loads() on untrusted input. Use subprocess with a list of arguments, json.loads or ast.literal_eval.
- For security tokens or secrets use the secrets module, not random.
- If a listed problem is only a style or design suggestion and not a real bug or security flaw, ignore it and leave that code as it is.

The user's requirement (follow it if it is given): {requirement}

Reply with ONLY the complete fixed Python code. No explanation, no markdown fences.

Problems:
{problems}

Code:
{code}
"""


def clean_code(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    if text.endswith("```"):
        text = text[:-3]
    return text.strip() + "\n"


def fix_code(code, bugs, issues):
    problems = []
    for b in bugs:
        if b.get("type") != "parse_error":
            problems.append(f"- Line {b.get('line')}: {b.get('explanation')}")
    for i in issues:
        if i.get("id") not in ("B404", "error"):
            problems.append(f"- Line {i['line']}: {i['issue']}")

    if not problems:
        return None, "no problems to fix"

    prompt = FIX_PROMPT.format(problems="\n".join(problems), code=code,
                               requirement="none given")
    fixed = clean_code(ask_llm(prompt))
    try:
        ast.parse(fixed)
    except SyntaxError as e:
        return fixed, "syntax error: " + str(e)
    return fixed, "syntax OK"