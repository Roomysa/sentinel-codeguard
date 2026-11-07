import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.bug_finder import find_bugs
from src.fix_pipeline import fix_and_verify
from src.llm_client import models_used, reset_used
from src.security_explainer import explain_findings
from src.security_scanner import scan_security
from src.static_analyzer import pylint_errors

PROVIDER = None  # None = full fallback chain
HERE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Sentinel CodeGuard")


class AnalyzeRequest(BaseModel):
    code: str


class FixRequest(BaseModel):
    code: str
    bugs: list = []
    security: list = []
    description: str = ""


def to_line(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@app.get("/")
def home():
    return FileResponse(os.path.join(HERE, "index.html"))


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    reset_used()
    bugs, bugs_error = [], None
    try:
        found = find_bugs(req.code, provider=PROVIDER)
        if isinstance(found, dict):
            found = [found]
        for b in found if isinstance(found, list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "parse_error":
                bugs_error = "The AI reply could not be read. Please try again."
                continue
            bugs.append({
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
        for e in pylint_errors(req.code):
            match = next((b for b in bugs if b["line"] == e["line"]), None)
            if match:
                match["confirmed"] = True
                match["source"] = "AI + pylint"
            else:
                bugs.append({
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
    try:
        for i in scan_security(req.code):
            if i.get("id") == "error":
                security_error = "Security scan failed: " + str(i.get("issue"))[:150]
                continue
            security.append({
                "line": to_line(i.get("line")),
                "id": str(i.get("id")),
                "severity": str(i.get("severity")).upper(),
                "issue": str(i.get("issue")),
                "detail": None,
            })
    except Exception as e:
        security_error = "Security scan failed: " + str(e)[:150]

    # AI and Bandit agree on a serious problem at the same line -> confirmed
    for b in bugs:
        if not b["confirmed"] and any(
                s["line"] == b["line"] and s["severity"] in ("HIGH", "MEDIUM")
                for s in security):
            b["confirmed"] = True
            b["source"] = "AI + Bandit"
    bugs.sort(key=lambda b: (not b["confirmed"], b["line"]))

    try:
        details = explain_findings(req.code, bugs, security, provider=PROVIDER)
    except Exception:
        details = {}
    for n, s in enumerate(security):
        s["detail"] = details.get(f"sec-{n}")
    for n, b in enumerate(bugs):
        b["detail"] = details.get(f"bug-{n}")

    return {"bugs": bugs, "security": security,
            "bugs_error": bugs_error, "security_error": security_error,
            "models_used": models_used()}


@app.post("/api/fix")
def fix(req: FixRequest):
    reset_used()
    try:
        result = fix_and_verify(req.code, req.bugs, req.security,
                                description=req.description, provider=PROVIDER)
    except Exception as e:
        result = {"fixed_code": None, "syntax_check": "", "verified": None,
                  "verify_message": "", "tries": 0, "checks": [], "remaining": [],
                  "no_action": False,
                  "error": "Fix failed: " + str(e)[:150]}
    result["models_used"] = models_used()
    return result