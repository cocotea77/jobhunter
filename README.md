# JobHunter

An AI-powered job-search product, built step by step to production
standard: a visitor uploads a resume, the system matches it against tens of
thousands of real job postings, and explains every match honestly.

This repository is also a course. Each step is documented in `docs/` in
plain language, assuming no prior knowledge, and each step's changes were
merged through a reviewed Pull Request with green automatic checks — so the
project's history itself teaches the workflow.

**Current step: 1 — the database, managed properly.**
Postgres with pgvector running in Docker; the first table; every schema
change made through versioned migration scripts from the very first table;
Continuous Integration that now starts a real database and proves every
migration applies, matches the models, and can be reversed.

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

Start the database, then apply the migrations:

```bash
docker compose up -d
alembic upgrade head
```

Full instructions for students: `docs/00_STEP0_WORKSPACE.md`, then
`docs/01_STEP1_DATABASE.md`.
