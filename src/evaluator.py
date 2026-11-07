import ast
import csv
import difflib
import os
import time

from src.bug_finder import find_bugs
from src.static_analyzer import pylint_hints

BUGGY_DIR = "Data/QuixBugs-master/python_programs"
CORRECT_DIR = "Data/QuixBugs-master/correct_python_programs"
SKIP = {"node.py"}
LIMIT = None
DELAY = 3
PROVIDER = "groq"
USE_PYLINT = True
OUTPUT_CSV = "results_llm_pylint_groq.csv" if USE_PYLINT else "results_llm_only_groq.csv"


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def code_lines(lines):
    """Line numbers with real code (no blanks, comments or docstrings)."""
    skip = set()
    try:
        tree = ast.parse("\n".join(lines))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                skip.update(range(node.lineno, node.end_lineno + 1))
    except SyntaxError:
        pass
    result = set()
    for n, line in enumerate(lines, start=1):
        text = line.strip()
        if text and not text.startswith("#") and n not in skip:
            result.add(n)
    return result


def real_bug_lines(buggy, correct):
    changed = set()
    matcher = difflib.SequenceMatcher(None, buggy, correct)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            changed.update(range(i1 + 1, i2 + 1))
        elif tag == "insert":
            changed.update({i1, i1 + 1})
    return changed & code_lines(buggy)


def clean_bugs(bugs):
    if isinstance(bugs, dict):
        bugs = [bugs]
    if not isinstance(bugs, list) or not all(isinstance(b, dict) for b in bugs):
        return None
    return bugs


def flagged_lines(bugs):
    result = set()
    for bug in bugs:
        try:
            result.add(int(bug.get("line")))
        except (TypeError, ValueError):
            pass
    return result


def call_with_retry(code, hints, tries=3):
    for attempt in range(tries):
        try:
            return find_bugs(code, provider=PROVIDER, hints=hints)
        except Exception as e:
            msg = str(e)
            print("  retry", attempt + 1, "|", msg[:80])
            if attempt == tries - 1:
                raise
            time.sleep(60 if "429" in msg else 10)


def main():
    names = sorted(
        f for f in os.listdir(BUGGY_DIR)
        if f.endswith(".py") and not f.endswith("_test.py") and f not in SKIP
        and os.path.exists(os.path.join(CORRECT_DIR, f))
    )
    if LIMIT:
        names = names[:LIMIT]

    rows = []
    fails = 0
    hinted = 0
    for name in names:
        buggy = read_lines(os.path.join(BUGGY_DIR, name))
        correct = read_lines(os.path.join(CORRECT_DIR, name))
        truth = real_bug_lines(buggy, correct)
        code = "\n".join(buggy)
        flagged = set()
        hit, false_alarms = False, 0

        hints = pylint_hints(code) if USE_PYLINT else ""
        if hints:
            hinted += 1

        start = time.time()
        try:
            bugs = clean_bugs(call_with_retry(code, hints))
            if bugs is None:
                status = "bad_format"
            elif any(b.get("type") == "parse_error" for b in bugs):
                status = "parse_error"
            elif not truth:
                status = "no_truth"
            else:
                status = "ok"
                flagged = flagged_lines(bugs)
                hit = bool(flagged & truth)
                false_alarms = len(flagged - truth)
        except Exception as e:
            status = "error"
            print("  error:", str(e)[:100])

        rows.append({"program": name, "hit": hit, "false_alarms": false_alarms,
                     "status": status, "pylint_hint": bool(hints)})
        print(name, "| hit:", hit, "| false alarms:", false_alarms, "|", status,
              "| pylint hint:", bool(hints))
        print("   LLM lines:", sorted(flagged), "| real bug lines:", sorted(truth))

        fails = fails + 1 if status == "error" else 0
        if fails >= 3:
            print("Stopping: 3 errors in a row. Run again later.")
            break

        if time.time() - start > 1:
            time.sleep(DELAY)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["program", "hit", "false_alarms", "status", "pylint_hint"])
        writer.writeheader()
        writer.writerows(rows)

    valid = [r for r in rows if r["status"] == "ok"]
    if valid:
        hits = sum(r["hit"] for r in valid)
        print(f"\nHit rate: {hits}/{len(valid)} = {hits / len(valid):.0%}")
        print("Total false alarms:", sum(r["false_alarms"] for r in valid))
    print("Programs where pylint gave hints:", hinted, "of", len(rows))
    others = {}
    for r in rows:
        if r["status"] != "ok":
            others[r["status"]] = others.get(r["status"], 0) + 1
    print("Not scored:", others or "none")


if __name__ == "__main__":
    main()