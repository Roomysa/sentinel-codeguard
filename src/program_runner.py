import re

from src import sandbox

# Errors that mean "the sandbox blocked it", not "your code is buggy"
SANDBOX_LIMIT = {
    "FileNotFoundError", "PermissionError", "IsADirectoryError",
    "NotADirectoryError", "OSError", "ConnectionError", "ConnectionRefusedError",
    "TimeoutError", "URLError", "gaierror", "ModuleNotFoundError", "ImportError",
    "BlockingIOError",
}
# Errors that do not depend on the input given, so they are certain bugs
CERTAIN = {"NameError", "UnboundLocalError", "SyntaxError", "IndentationError",
           "TabError"}


def run_program(code, stdin_text="", timeout=15):
    out = sandbox.run_script({"main.py": code}, "main.py", timeout=timeout,
                             stdin_text=stdin_text, require_sandbox=True)
    result = {"status": "", "exc_type": "", "line": None, "message": "",
              "certain": False, "stdout": out["stdout"][:4000],
              "stderr": out["stderr"][-1500:], "sandboxed": out["sandboxed"]}

    if out.get("blocked"):
        result["status"] = "no_sandbox"
        return result
    if out["timed_out"]:
        result["status"] = "timeout"
        return result
    if out["returncode"] == 0:
        result["status"] = "ran_ok"
        return result

    lines = [x for x in out["stderr"].strip().splitlines() if x.strip()]
    last = lines[-1] if lines else ""
    exc = last.split(":", 1)[0].strip().split(".")[-1]
    result["exc_type"] = exc
    result["message"] = last.split(":", 1)[1].strip() if ":" in last else ""
    found = re.findall(r'File "[^"]*main\.py", line (\d+)', out["stderr"])
    result["line"] = int(found[-1]) if found else None

    if exc == "EOFError":
        result["status"] = "needs_input"
    elif exc in SANDBOX_LIMIT:
        result["status"] = "sandbox_limit"
    elif exc.endswith(("Error", "Exception")):
        result["status"] = "crash"
        result["certain"] = exc in CERTAIN
    else:
        result["status"] = "exit_nonzero"
    return result
