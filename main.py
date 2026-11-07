import os
import sys

from src.bug_finder import find_bugs
from src.fixer import fix_code
from src.security_scanner import scan_security


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    want_fix = "--fix" in sys.argv
    if not args:
        print("Usage: python main.py <file.py> [--fix]")
        return

    path = args[0]
    try:
        with open(path, encoding="utf-8") as f:
            code = f.read()
    except OSError as e:
        print("Cannot read file:", e)
        return

    bugs, issues = [], []

    print("=== BUGS (AI review) ===")
    try:
        bugs = [b for b in find_bugs(code) if isinstance(b, dict)]
        if not bugs:
            print("No bugs found.")
        for b in bugs:
            print(f"  Line {b.get('line')}: [{b.get('type')}] {b.get('explanation')}")
    except Exception as e:
        print("AI review failed:", str(e)[:150])

    print()
    print("=== SECURITY ISSUES (Bandit) ===")
    try:
        issues = scan_security(code)
        if not issues:
            print("No security issues found.")
        for i in issues:
            print(f"  Line {i['line']}: [{i['severity']}] {i['issue']}")
    except Exception as e:
        print("Security scan failed:", str(e)[:150])

    if want_fix:
        print()
        print("=== FIX ===")
        try:
            fixed, check = fix_code(code, bugs, issues)
        except Exception as e:
            print("Fix failed:", str(e)[:150])
            return
        if fixed is None:
            print("Nothing to fix.")
            return
        base, ext = os.path.splitext(path)
        out_path = base + "_fixed" + ext
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(fixed)
        print("Fixed code saved to:", out_path)
        print("Syntax check:", check)


if __name__ == "__main__":
    main()