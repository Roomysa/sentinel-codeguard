import os
import subprocess
import sys
import tempfile
import threading
import uuid

IMAGE = "python:3.14-slim"
MAX_OUT = 20000
_state = threading.local()


def docker_available():
    """True only if Docker works and the sandbox image is already pulled."""
    if os.getenv("CODEGUARD_SANDBOX", "").lower() == "off":
        return False
    try:
        r = subprocess.run(["docker", "image", "inspect", IMAGE],
                           capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def last_sandboxed():
    return getattr(_state, "sandboxed", None)


def _clip(text):
    text = text or ""
    return text if len(text) <= MAX_OUT else text[:MAX_OUT] + "\n...[output cut]"


def _run_docker(folder, script, args, timeout, stdin_text):
    name = "codeguard-" + uuid.uuid4().hex[:12]
    cmd = ["docker", "run", "--rm", "-i", "--name", name,
           "--network", "none",
           "--memory", "256m", "--memory-swap", "256m",
           "--cpus", "1", "--pids-limit", "64",
           "--read-only", "--tmpfs", "/tmp:rw,size=16m",
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp",
           "-v", f"{folder}:/work:ro", "-w", "/work"]
    if hasattr(os, "getuid"):
        cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
    cmd += [IMAGE, "python", script, *args]
    try:
        r = subprocess.run(cmd, input=stdin_text or "", capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
        return {"stdout": "", "stderr": "", "returncode": None,
                "timed_out": True, "sandboxed": True}
    if r.returncode == 125 or (r.stderr or "").startswith("docker:"):
        return None  # Docker itself failed, caller falls back
    return {"stdout": _clip(r.stdout), "stderr": _clip(r.stderr),
            "returncode": r.returncode, "timed_out": False, "sandboxed": True}


def _run_local(folder, script, args, timeout, stdin_text):
    try:
        r = subprocess.run([sys.executable, script, *args], cwd=folder,
                           input=stdin_text or "", capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "", "returncode": None,
                "timed_out": True, "sandboxed": False}
    return {"stdout": _clip(r.stdout), "stderr": _clip(r.stderr),
            "returncode": r.returncode, "timed_out": False, "sandboxed": False}


def run_script(files, script, args=(), timeout=30, stdin_text=None):
    """Write files to a temp folder and run `python script args`.
    Runs inside Docker when possible, otherwise in a plain subprocess."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        for name, text in files.items():
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                f.write(text)
        out = None
        if docker_available():
            out = _run_docker(folder, script, list(args), timeout, stdin_text)
        if out is None:
            out = _run_local(folder, script, list(args), timeout, stdin_text)
    _state.sandboxed = out["sandboxed"]
    return out
