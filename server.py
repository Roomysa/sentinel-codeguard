import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.bug_finder import find_bugs
from src.fix_pipeline import fix_and_verify
from src.llm_client import models_used, reset_used
from src.program_runner import clean_project, summarize_others
from src.security_explainer import explain_findings
from src.security_scanner import scan_security
from src.static_analyzer import pylint_errors, pylint_errors_project

PROVIDER = None  # None = full fallback chain
HERE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Sentinel CodeGuard")


class FileItem(BaseModel):
    name: str
    code: str = ""


class AnalyzeRequest(BaseModel):
    code: str = ""
    files: list[FileItem] = []
    main: str = ""
    description: str = ""


class FixRequest(BaseModel):
    code: str = ""
    files: list[FileItem] = []
    main: str = ""
    bugs: list = []
    security: list = []
    description: str = ""


def to_line(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def project_from(req):
    files = [f.model_dump() for f in req.files]
    return clean_project(files, req.code, req.main)


@app.get("/")
def home():
    return FileResponse(os.path.join(HERE, "index.html"))


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    reset_used()
    project, main, err = project_from(req)
    if err:
        return {"bugs": [], "security": [], "bugs_error": err, "security_error": None,
                "models_used": [], "main": "", "files": []}
    code = project[main]
    multi = len(project) > 1

    context = ""
    description = (req.description or "").strip()
    if description:
        context += ("\nThe user says this code should: " + description[:300]
                    + "\nReport a requirement problem only if the code clearly does not do this.\n")
    context += summarize_others(project, main)

    bugs, bugs_error = [], None
    try:
        found = find_bugs(code, provider=PROVIDER, context=context)
        if isinstance(found, dict):
            found = [found]
        for b in found if isinstance(found, list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "parse_error":
                bugs_error = "The AI reply could not be read. Please try again."
                continue
            bugs.append({
                "file": main,
                "line": to_line(b.get("line")),
                "type": str(b.get("type") or "bug"),
                "explanation": str(b.get("explanation") or ""),
                "confirmed": False,
                "source": "AI",
                "detail": None,
            })
    except Exception as e:
        bugs_error = "AI review failed: " + str(e)[:150]

    try:
        if multi:
            errors = pylint_errors_project(project)
        else:
            errors = [dict(e, file=main) for e in pylint_errors(code)]
        for e in errors:
            match = next((b for b in bugs
                          if e["file"] == main and b["line"] == e["line"]), None)
            if match:
                match["confirmed"] = True
                match["source"] = "AI + pylint"
            else:
                bugs.append({
                    "file": e["file"],
                    "line": e["line"],
                    "type": e["symbol"],
                    "explanation": e["issue"],
                    "confirmed": True,
                    "source": "pylint",
                    "detail": None,
                })
    except Exception:
        pass

    security, security_error = [], None
    for name, text in project.items():
        try:
            for i in scan_security(text):
                if i.get("id") == "error":
                    security_error = ("Security scan failed (" + name + "): "
                                      + str(i.get("issue"))[:120])
                    continue
                security.append({
                    "file": name,
                    "line": to_line(i.get("line")),
                    "id": str(i.get("id")),
                    "severity": str(i.get("severity")).upper(),
                    "issue": str(i.get("issue")),
                    "detail": None,
                })
        except Exception as e:
            security_error = "Security scan failed: " + str(e)[:150]

    # AI and Bandit agree on a serious problem at the same line of the main file
    for b in bugs:
        if not b["confirmed"] and b["file"] == main and any(
                s["file"] == main and s["line"] == b["line"]
                and s["severity"] in ("HIGH", "MEDIUM") for s in security):
            b["confirmed"] = True
            b["source"] = "AI + Bandit"
    bugs.sort(key=lambda b: (not b["confirmed"], b["file"] != main, b["line"]))

    # Explanations are written for the main file only
    bugs_view = [b if b["file"] == main else dict(b, confirmed=False) for b in bugs]
    sec_view = [s if s["file"] == main else dict(s, severity="LOW") for s in security]
    try:
        details = explain_findings(code, bugs_view, sec_view, provider=PROVIDER)
    except Exception:
        details = {}
    for n, s in enumerate(security):
        s["detail"] = details.get(f"sec-{n}")
    for n, b in enumerate(bugs):
        b["detail"] = details.get(f"bug-{n}")

    return {"bugs": bugs, "security": security,
            "bugs_error": bugs_error, "security_error": security_error,
            "models_used": models_used(), "main": main, "files": list(project)}


@app.post("/api/fix")
def fix(req: FixRequest):
    reset_used()
    project, main, err = project_from(req)
    if err:
        return {"error": err, "models_used": []}
    try:
        result = fix_and_verify(project[main], req.bugs, req.security,
                                description=req.description, provider=PROVIDER,
                                files=project, main=main)
    except Exception as e:
        result = {"fixed_code": None, "syntax_check": "", "verified": None,
                  "verify_message": "", "tries": 0, "checks": [], "remaining": [],
                  "missing_modules": [], "other_files": [], "sandboxed": None,
                  "no_action": False,
                  "error": "Fix failed: " + str(e)[:150]}
    result["main"] = main
    result["models_used"] = models_used()
    return result
