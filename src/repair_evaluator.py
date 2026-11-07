import csv
import os
import time

from src.repair import repair
from src.verifier import QUIXBUGS_DIR

BUGGY_DIR = os.path.join(QUIXBUGS_DIR, "python_programs")
TEST_DIR = os.path.join(QUIXBUGS_DIR, "python_testcases")
SKIP = {"node.py"}
LIMIT = None
DELAY = 3
PROVIDER = "groq"
OUTPUT_CSV = "results_repair_groq.csv"


def repair_with_retry(name, code, tries=3):
    for attempt in range(tries):
        try:
            return repair(name, code, provider=PROVIDER)
        except Exception as e:
            msg = str(e)
            print("  retry", attempt + 1, "|", msg[:80])
            if attempt == tries - 1:
                raise
            time.sleep(60 if "429" in msg else 10)


def main():
    names = sorted(
        f[:-3] for f in os.listdir(BUGGY_DIR)
        if f.endswith(".py") and not f.endswith("_test.py") and f not in SKIP
        and os.path.exists(os.path.join(TEST_DIR, "test_" + f))
    )
    if LIMIT:
        names = names[:LIMIT]

    rows = []
    fails = 0
    for name in names:
        with open(os.path.join(BUGGY_DIR, name + ".py"), encoding="utf-8") as f:
            code = f.read()

        start = time.time()
        try:
            result = repair_with_retry(name, code)
            if result["passed"]:
                status = "fixed"
            elif result["tries"] == 0:
                status = "no_bugs_found"
            else:
                status = "not_fixed"
            tries = result["tries"]
            note = result["note"]
        except Exception as e:
            status, tries, note = "error", 0, str(e)

        note = " ".join(note.split())[:150]
        rows.append({"program": name, "status": status, "tries": tries, "note": note})
        print(name, "|", status, "| tries:", tries)

        fails = fails + 1 if status == "error" else 0
        if fails >= 3:
            print("Stopping: 3 errors in a row. Run again later.")
            break

        if time.time() - start > 1:
            time.sleep(DELAY)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["program", "status", "tries", "note"])
        writer.writeheader()
        writer.writerows(rows)

    attempted = [r for r in rows if r["status"] != "error"]
    fixed = [r for r in rows if r["status"] == "fixed"]
    print()
    print(f"Fixed (tests passed): {len(fixed)}/{len(attempted)}")
    if fixed:
        print("Average tries for fixed ones:", round(sum(r["tries"] for r in fixed) / len(fixed), 2))
    counts = {}
    for r in rows:
        if r["status"] != "fixed":
            counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("Not fixed:", counts or "none")


if __name__ == "__main__":
    main()