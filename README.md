# JobPilot

An AI-powered job-search product, built step by step to production
standard: a visitor uploads a resume, the system matches it against tens of
thousands of real job postings, and explains every match honestly.

This repository is also a course. Each step is documented in `docs/` in
plain language, assuming no prior knowledge, and each step's changes were
merged through a reviewed Pull Request with green automatic checks — so the
project's history itself teaches the workflow.

**Current step: 0 — the professional workspace.**
A running web server, a test suite, a code style checker, and Continuous
Integration that blocks broken changes from reaching the main branch.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload
```

Then open http://localhost:8000/health — you should see the service
identify itself. Run the checks the same way GitHub will:

```bash
ruff check .
pytest -v
```

Full instructions for students: `docs/00_STEP0_WORKSPACE.md`.
