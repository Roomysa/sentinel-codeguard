import json

from src.llm_client import ask_llm

FENCE = "`" * 3
MAX_ITEMS = 8
SERIOUS = ("HIGH", "MEDIUM")

PROMPT = """You are a security teacher for beginners.
Explain each finding below in simple English.
Reply ONLY with a JSON list. No extra text.
Each item must have:
- "key": copy the key exactly
- "explanation": ONE short sentence saying what the finding means
If a finding says detail=yes, the item must ALSO have:
- "risk": ONE short sentence saying what an attacker or a failure could cause
- "fix": a secure code example of at most 3 lines, written as one string
If a finding says detail=no, do NOT include "risk" or "fix".

Code:
{code}

Findings:
{findings}
"""


def explain_findings(code, bugs, security, provider=None):
    items = []
    for n, s in enumerate(security):
        if s.get("id") != "error" and str(s.get("severity", "")).upper() in SERIOUS:
            items.append((f"sec-{n}", True,
                          f"{s['severity']} {s['id']} line {s['line']}: {s['issue']}"))
    for n, b in enumerate(bugs):
        if b.get("confirmed"):
            items.append((f"bug-{n}", True,
                          f"confirmed bug line {b['line']}: {b['explanation']}"))
    for n, s in enumerate(security):
        if s.get("id") != "error" and str(s.get("severity", "")).upper() not in SERIOUS:
            items.append((f"sec-{n}", False,
                          f"{s['severity']} {s['id']} line {s['line']}: {s['issue']}"))
    items = items[:MAX_ITEMS]
    if not items:
        return {}

    findings = "\n".join(
        f"key={key} | detail={'yes' if detail else 'no'} | {text}"
        for key, detail, text in items)
    reply = ask_llm(PROMPT.format(code=code, findings=findings),
                    provider=provider).strip()
    reply = reply.removeprefix(FENCE + "json").removeprefix(FENCE).removesuffix(FENCE).strip()
    try:
        parsed = json.loads(reply)
    except json.JSONDecodeError:
        return {}

    wants_detail = {key: detail for key, detail, _ in items}
    result = {}
    if isinstance(parsed, list):
        for it in parsed:
            if not isinstance(it, dict) or it.get("key") not in wants_detail:
                continue
            key = it["key"]
            entry = {"explanation": str(it.get("explanation") or "")[:300],
                     "risk": "", "fix": ""}
            if wants_detail[key]:
                entry["risk"] = str(it.get("risk") or "")[:300]
                entry["fix"] = str(it.get("fix") or "")[:400]
            result[key] = entry
    return result