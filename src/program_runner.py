import ast
import re
import sys

from src import sandbox

STDLIB = set(sys.stdlib_module_names)
SANDBOX_PACKAGES = set()  # extra packages baked into the sandbox image (none yet)

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


def missing_modules(code):
    """Imported modules that are not in the standard library (so not in the sandbox)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return sorted(n for n in names
                  if n not in STDLIB and n not in SANDBOX_PACKAGES and n != "__future__")


def missing_message(mods):
    names = ", ".join(mods)
    return (f"Your code uses {names}, which is not available in the sandbox "
            "(no internet, limited packages). Static checks ran; "
            "the program itself was not executed.")


def run_program(code, stdin_text="", timeout=15):
    result = {"status": "", "exc_type": "", "line": None, "message": "",
              "certain": False, "stdout": "", "stderr": "", "sandboxed": False,
              "missing": []}

    missing = missing_modules(code)
    if missing:
        result["status"] = "missing_packages"
        result["message"] = missing_message(missing)
        result["missing"] = missing
        return result

    out = sandbox.run_script({"main.py": code}, "main.py", timeout=timeout,
                             stdin_text=stdin_text, require_sandbox=True)
    result["stdout"] = out["stdout"][:4000]
    result["stderr"] = out["stderr"][-1500:]
    result["sandboxed"] = out["sandboxed"]

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
