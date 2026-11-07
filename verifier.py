import os
import shutil
import subprocess
import sys
import tempfile

QUIXBUGS_DIR = "Data/QuixBugs-master"
COPY_ITEMS = ["python_programs", "python_testcases", "json_testcases"]


def verify_fix(program, fixed_code, timeout=30):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        for item in COPY_ITEMS:
            shutil.copytree(
                os.path.join(QUIXBUGS_DIR, item),
                os.path.join(tmp, item),
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        shutil.copy(os.path.join(QUIXBUGS_DIR, "conftest.py"), tmp)

        target = os.path.join(tmp, "python_programs", program + ".py")
        with open(target, "w", encoding="utf-8") as f:
            f.write(fixed_code)

        test_file = os.path.join("python_testcases", "test_" + program + ".py")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", test_file,
                 "-q", "-x", "--tb=short", "--disable-warnings", "-rN",
                 "-p", "no:cacheprovider"],
                cwd=tmp,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"timeout after {timeout}s (possible infinite loop)"

    output = (result.stdout + result.stderr).strip()
    if result.returncode == 0:
        return True, "all tests passed"
    return False, "tests failed:\n" + output[-800:]