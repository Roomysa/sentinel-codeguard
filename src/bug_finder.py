import json

from src.llm_client import ask_llm

FENCE = "`" * 3

PROMPT_TEMPLATE = """You are a Python code reviewer.
Find bugs in the code below.
Reply ONLY with a JSON list. No extra text.
Each item must have: "line" (number), "type" (short bug type), "explanation" (one sentence).
If there are no bugs, reply with [].
{hints}
Code:
{code}
"""


def add_line_numbers(code):
    lines = code.splitlines()
    return "\n".join(f"{i}: {line}" for i, line in enumerate(lines, start=1))


def find_bugs(code, provider=None, hints="", context=""):
    prompt = PROMPT_TEMPLATE.format(hints=hints + context, code=add_line_numbers(code))
    reply = ask_llm(prompt, provider=provider).strip()
    reply = reply.removeprefix(FENCE + "json").removeprefix(FENCE).removesuffix(FENCE).strip()
    try:
        return json.loads(reply)
    except json.JSONDecodeError:
        return [{"line": None, "type": "parse_error", "explanation": reply}]
