# Sentinel CodeGuard
**AI Python Bug Finder, Fixer and Security Checker**

Internship final project (Week 6) by Roomysa Yameen


## What it does
You give the tool a Python file. It:
1. Asks an AI model to find bugs (line number, type, explanation).
2. Runs Bandit to find security issues.
3. On request (`--fix`), asks the AI to write a fixed version and saves it as a new file. Your original file is never changed.

## Why
AI is good at logic bugs, and Bandit is good at known security patterns. Each one misses things the other finds, so the tool uses both.

## How it works
```
Python file -> AI review (bugs) ----+
            -> Bandit (security) ---+--> report --> (--fix) fixed copy + syntax check

Evaluation only (QuixBugs):
buggy program -> AI finds bugs (or the tests do) -> AI writes a fix
              -> run real tests on a temp copy -> if they fail, send the error back (max 3 tries)
```
- `src/verifier.py`: puts the fixed code in a temporary copy of QuixBugs and runs its pytest tests in a separate process with a 30 second timeout (stops infinite loops).
- `src/repair.py`: fix and retry loop. If the AI finds no bug, the tests decide if the code is broken and their error is sent to the AI.
- `src/repair_evaluator.py`: runs the repair loop on all QuixBugs programs.

## Usage
```
python main.py demo_buggy.py            # find bugs and security issues
python main.py demo_buggy.py --fix      # also save demo_buggy_fixed.py (syntax check only)
python -m src.evaluator                 # bug finding accuracy on QuixBugs
python -m src.repair_evaluator          # fix and verify on QuixBugs
```

## Results

**1. Bug finding on QuixBugs (AI only, exact line must match)**
- Model: `openai/gpt-oss-120b` (via Groq), 40 programs
- Hit rate: **33/40 (82%)**, false alarms: **26**

**2. Fix and verify on QuixBugs (real tests are the judge, max 3 tries)**
- Fixed: **39/40 (97.5%)**, average tries for fixed programs: **1.08**
- 3 programs needed a second try (`bitcount`, `minimum_spanning_tree`, `subsequences`)
- Not fixed: `topological_ordering`
- Bugs found by the AI review: [39] programs, found by the tests when the AI found none: [1] programs

**3. Security fix on `demo_buggy.py` (Bandit before and after)**

| | Before fix | After fix |
|---|---|---|
| HIGH (`shell=True`) | 1 | 0 |
| Hardcoded password | 1 | 0 |
| LOW warnings | 2 | 3 |

**4. Pylint**
Pylint error checks found nothing in all 40 QuixBugs programs. These are logic bugs that static analysis cannot see, which is why an AI reviewer is needed.

Screenshots: [add screenshots here]

## Challenges
- **Free API limits:** OpenRouter hit its daily limit, Gemini gave timeouts, 503 and 429 errors. Solution: provider fallback chain, answer cache, retries with waiting.
- **Wrong scoring at first:** the real bug lines included comments and docstrings. Solution: score only real code lines.
- **Model names change:** a Groq model disappeared. Solution: list the available models from the API.
- **Infinite loops:** the buggy `bitcount` hung a test for 5 minutes. Solution: run tests in a separate process with a timeout.
- **AI found no bug:** `bitcount` was missed by the AI review. Solution: let the failing tests describe the problem to the AI.

## Limitations
- Python only, mostly single files.
- QuixBugs is a public dataset, so the model may have seen it. Results on unseen code may be lower.
- The real tests both guide the fix (their error goes back to the AI) and judge it. Real users often have no tests, so `--fix` in `main.py` only checks syntax and does not use the verify loop yet.
- Passing tests does not mean a minimal fix. For `bitcount` the AI rewrote the whole function instead of changing one line.
- Tests run on the local machine in a separate process with a timeout. This is not a real sandbox.
- One model and one run per experiment.
- The AI sometimes flags extra lines (false alarms).

## Future improvements
- Run fixes in a real sandbox (Docker) with limited access
- Connect the verify loop to `main.py` (user gives an example input and output, or the AI writes tests)
- Prefer smaller fixes that change fewer lines
- RAG with Python docs and common bug patterns
- Fine-tune a code model with LoRA on Colab
- More models and repeated runs to compare results
- Support more languages and multi-file projects

## What I learned
- [Prompting an AI model to return structured JSON]
- [Measuring a system with a test set instead of guessing]
- [Handling API rate limits and fallbacks]
- [Why AI output must be validated, and why tests are a better judge than the AI]
- [Add your own points]