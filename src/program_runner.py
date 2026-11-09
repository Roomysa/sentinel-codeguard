import ast
import re
import sys

from src import sandbox

STDLIB = set(sys.stdlib_module_names)
SANDBOX_PACKAGES = set()  # extra packages baked into the sandbox image (none yet)
RESERVED = {"runner", "target", "checks"}
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.py$")
MAX_FILES = 10
MAX_TOTAL = 200_000

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


def clean_project(files, code="", main=""):
    """Validate the uploaded files. Returns (project dict, main name, error text)."""
    items = []
    for f in files or []:
        if isinstance(f, dict):
            items.append((str(f.get("name", "")), str(f.get("code", ""))))
    if not items:
        if not (code or "").strip():
            return {}, "", "No code was given."
        return {"main.py": code}, "main.py", ""
    if len(items) > MAX_FILES:
        return {}, "", f"Too many files (maximum {MAX_FILES})."
    project = {}
    for name, text in items:
        name = name.strip()
        if not NAME_RE.match(name):
            return {}, "", (f"File name '{name[:40]}' is not allowed. "
                            "Use plain names like utils.py (letters, digits and underscore).")
        stem = name[:-3]
        if stem in RESERVED:
            return {}, "", f"File name '{name}' is reserved. Please rename it."
        if stem in STDLIB:
            return {}, "", (f"File name '{name}' is not allowed because it would "
                            "shadow a standard module. Please rename it.")
        if name in project:
            return {}, "", f"Duplicate file name '{name}'."
        project[name] = text
    if sum(len(t.encode("utf-8")) for t in project.values()) > MAX_TOTAL:
        return {}, "", "The files are too large (maximum 200 KB in total)."
    if not any(t.strip() for t in project.values()):
        return {}, "", "The files are empty."
    main = (main or "").strip()
    if main not in project:
        main = "main.py" if "main.py" in project else next(iter(project))
    return project, main, ""


def summarize_others(project, main):
    """Short description of the other files, so the AI knows what they offer."""
    lines = []
    for name, text in project.items():
        if name == main:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            lines.append(f"- {name}: (could not be parsed)")
            continue
        defs = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = ", ".join(a.arg for a in node.args.args)
                defs.append(f"def {node.name}({args})")
            elif isinstance(node, ast.ClassDef):
                defs.append(f"class {node.name}")
        lines.append(f"- {name}: " + ("; ".join(defs[:12]) if defs else "no functions or classes"))
    if not lines:
        return ""
    return ("\nOther files in the project (for reference only, "
            "do not report problems in them):\n" + "\n".join(lines) + "\n")


def missing_modules(code, local=()):
    """Imported modules that are neither standard library nor the user's own files."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    own = {n[:-3] if n.endswith(".py") else n for n in local}
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return sorted(n for n in names
                  if n not in STDLIB and n not in SANDBOX_PACKAGES
                  and n not in own and n != "__future__")


def missing_message(mods):
    names = ", ".join(mods)
    return (f"Your code uses {names}, which is not available in the sandbox "
            "(no internet, limited packages). Static checks ran; "
            "the program itself was not executed.")


def run_program(code, stdin_text="", timeout=15, files=None, main="main.py"):
    result = {"status": "", "exc_type": "", "line": None, "file": None,
              "message": "", "certain": False, "stdout": "", "stderr": "",
              "sandboxed": False, "missing": []}

    project = dict(files or {})
    project[main] = code

    missing = missing_modules(code, list(project))
    if missing:
        result["status"] = "missing_packages"
        result["message"] = missing_message(missing)
        result["missing"] = missing
        return result

    out = sandbox.run_script(project, main, timeout=timeout,
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
    found = re.findall(r'File "[^"]*?([A-Za-z_][A-Za-z0-9_]*\.py)", line (\d+)',
                       out["stderr"])
    mine = [(n, int(ln)) for n, ln in found if n in project]
    if mine:
        result["file"], result["line"] = mine[-1]

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
