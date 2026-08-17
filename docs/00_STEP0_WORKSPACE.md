# Step 0 — The Professional Workspace

Welcome. Over the coming steps you will build JobPilot: a real, public
website where anyone can upload a resume and receive honestly-explained
matches against tens of thousands of live job postings, powered by AI
agents you will build yourself. By the end, the project will be deployed,
monitored, protected against abuse and runaway costs, and operated with
real users — the kind of project that answers the interview question
"have you built production AI products, or only demos?"

Step 0 contains **no AI and no product features**. It builds the workspace
that every professional software team works inside. That is a deliberate
choice: the single most visible difference between a student project and a
professional one is not the features — it is the discipline around them.
You will finish this step with a running web server, an automatic test
suite, and a GitHub repository that physically refuses to accept broken
changes.

Time needed: about two to three hours, done carefully.

---

## 1. Words used in this course (read once, refer back any time)

- **Repository ("repo")** — one folder, tracked by the Git version-control
  program, containing all the project's code and its entire change history.
- **Commit** — one saved snapshot of the code, with a short message saying
  what changed. The history of a project is a chain of commits.
- **Branch** — a separate working line inside the repository. You make
  changes on a branch so the official copy stays safe until you are done.
- **Main branch ("main")** — the official copy. Our permanent rule:
  **main always works.** Anyone must be able to download main at any moment
  and run it successfully.
- **Pull Request** — a proposal on GitHub: "please take the changes from my
  branch into main." It displays every changed line for review before the
  change is accepted.
- **Merge** — accepting a Pull Request, making its changes part of main.
- **Continuous Integration ("CI")** — an automatic checker. Every Pull
  Request triggers GitHub to run our checks on a fresh, clean computer.
  A failing check blocks the merge button.
- **Test** — a small program that uses the application the way a user would
  and verifies the result is exactly what we promised. The `tests/` folder
  holds all of them; the command `pytest` runs all of them.
- **Endpoint** — one web address the application answers, such as
  `/health`. The web framework (FastAPI) turns Python functions into
  endpoints.
- **Environment variable** — a named value provided by the operating
  system, used to configure the application from outside the code. This is
  how the same code behaves correctly on your laptop and on the live server.

---

## 2. What is in this delivery, file by file

| File | What it is |
|------|------------|
| `app/config.py` | The application's configuration. Every changeable value lives here and can be overridden by environment variables. Read its comments — they explain the priority order. |
| `app/main.py` | The web application. One endpoint so far: `/health`. Its comments explain why a health endpoint comes before any feature. |
| `tests/test_health.py` | Two tests proving `/health` answers correctly. Read this file first — its opening comment explains what a test is. |
| `tests/test_config.py` | Three tests proving configuration defaults work, environment variables override them, and a misspelled value fails loudly instead of being silently ignored. |
| `requirements.txt` | The libraries the application needs to run, each with a comment saying why. |
| `requirements-dev.txt` | The tools used only during development: the test runner and the style checker. |
| `ruff.toml` | Settings for the code style checker. |
| `.gitignore` | The list of files Git must never store: secrets, caches, and personal editor settings. Read its comments. |
| `.env.example` | A template for local configuration. You copy it to `.env` (which Git ignores) and put real values there. In Step 0 there are no secrets yet — the file exists so the habit exists before the first real secret arrives. |
| `conftest.py` | A small marker so the test runner finds the project on any machine. |
| `.github/workflows/ci.yml` | The Continuous Integration instructions GitHub follows on every Pull Request. Read its comments. |
| `README.md` | The front page of the repository. |

---

## 3. Get it running on your computer

You need: Python 3.12, Git, and PyCharm (the free Community Edition is
enough). On Windows, use the PyCharm terminal for all commands below.

**3.1 — Unzip** this delivery into a folder named `jobpilot`.

**3.2 — Open it in PyCharm:** File → Open → choose the `jobpilot` folder.

**3.3 — Create the project's own Python environment.** Every project gets
its own private set of installed libraries, so projects can never conflict
with each other. In PyCharm: Settings → Project → Python Interpreter →
Add Interpreter → Virtualenv Environment → New, location `.venv` inside
the project, base interpreter Python 3.12. (Our `.gitignore` already
excludes `.venv` — the environment is rebuilt on each machine, never
stored in the repository.)

**3.4 — Install everything.** In the PyCharm terminal:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

**3.5 — Start the server:**

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000/health in your browser. Expected answer:

```json
{"status": "ok", "app": "JobPilot", "version": "0.1.0", "environment": "development"}
```

You are looking at a live web service answering a real HTTP request.
Stop the server with Ctrl+C.

**3.6 — Run the checks yourself,** exactly as GitHub will run them later:

```bash
ruff check .
pytest -v
```

Expected: "All checks passed!" and "5 passed". If both are green on your
machine, they will be green on GitHub's machine — same commands, same
files.

**3.7 — Save yourself future typing (recommended).** In PyCharm:
Run → Edit Configurations → "+" → create two entries:
- *pytest* configuration named "tests", pointed at the `tests` folder.
- *Python* configuration named "API server": module `uvicorn`,
  parameters `app.main:app --reload`.

From now on, you start the tests or the server with one click.

---

## 4. Put the project on GitHub

**4.1 — Turn the folder into a repository and make the first commit:**

```bash
git init
git add .
git commit -m "Step 0: workspace, health endpoint, tests, CI"
git tag step-0
```

The tag is a permanent bookmark. When the project is finished, anyone can
travel back to `step-0` and replay the whole course commit by commit.

**4.2 — Create the GitHub repository.** On github.com: New repository,
name `jobpilot`, visibility **Public** (it is a portfolio piece — public
is the point). Important: do NOT let GitHub add any starter files (no
README, no .gitignore from their side) — we already have ours.

**4.3 — Connect and upload:**

```bash
git remote add origin https://github.com/YOUR-USERNAME/jobpilot.git
git push -u origin main --tags
```

**4.4 — Watch the first automatic check.** On GitHub, open the **Actions**
tab. Within about two minutes, a green check mark appears next to your
commit. Pause on what that mark means: a computer that is not yours, with
nothing pre-installed, downloaded your code, installed it from your
requirements files, and passed every test. That is the definition of
"reproducible" — and it is the first thing this course can prove.

---

## 5. Protect the main branch

On GitHub: Settings → Branches → Add branch ruleset (older interface:
"Add rule"). Target: `main`. Turn on:

- **Require a pull request before merging**
- **Require status checks to pass** → select the check named `checks`

From this moment, nobody — including you, the owner — can change main
directly. Every change must arrive through a Pull Request with green
checks. We enforce this even when working completely alone, for two
reasons. First, reading your own change in the Pull Request view, as a
reviewer would, catches real mistakes with surprising regularity. Second,
the habit itself is the professional skill; interviewers recognize it
instantly in a repository's history.

---

## 6. The proof exercise: watch the system reject a bad change

Do not skip this. Seeing the protection work once teaches more than any
explanation.

**6.1 — Make a branch with a deliberate mistake:**

```bash
git checkout -b exercise/prove-ci-blocks-mistakes
```

Open `tests/test_health.py` and add this line at the very top:
`import os` — an import that is never used. An unused import is exactly
the kind of small carelessness the style checker exists to catch.

```bash
git add . && git commit -m "Exercise: deliberately add an unused import"
git push -u origin exercise/prove-ci-blocks-mistakes
```

**6.2 — Open a Pull Request.** GitHub will show a banner suggesting it;
click "Compare & pull request", then "Create pull request".

**6.3 — Watch it fail.** Within a minute or two: a red cross. Click
"Details" and read the checker's message — it names the file, the line,
and the problem. Notice the merge button is blocked. This is the machinery
that will one day stop a broken AI prompt from reaching your real users.

**6.4 — Fix it and watch it pass.** Remove the line, then:

```bash
git add . && git commit -m "Remove the unused import"
git push
```

The same Pull Request re-checks itself and turns green.

**6.5 — Merge properly.** Choose **"Squash and merge"** (it combines the
branch's commits into one clean commit on main), confirm, then click
"Delete branch". Back in the terminal:

```bash
git checkout main
git pull
```

You have completed one full professional change cycle: branch → change →
automatic verification → review → merge → clean up. Every step in the rest
of this course travels exactly this road.

---

## 7. The working rule for every future step

1. Start from an up-to-date main: `git checkout main && git pull`
2. Create a branch named after the step: `git checkout -b step/1-database`
3. Make small commits with clear messages written as instructions
   ("Add jobs table"), never vague words ("changes", "fix stuff").
4. Push and open a Pull Request. In its description write three things:
   **what** changed, **why**, and **how you verified it** (paste the real
   output of your checks).
5. Wait for green checks, read your own change once as a reviewer, then
   "Squash and merge" and delete the branch.

**Main always works.** That sentence is the whole discipline.

---

## 8. Check your understanding (answers at the bottom)

1. Why is the `.env` file ignored by Git while `.env.example` is committed?
2. Your tests pass on your laptop but fail on GitHub. What is the most
   likely category of cause?
3. Why does a misspelled `ENVIRONMENT` value crash the application at
   startup instead of falling back to "development"?
4. Why do we require Pull Requests even when working alone?

---

*Answers: (1) `.env` will contain real secrets, and anything committed to
a public repository is public forever, even if deleted later; the example
file shares the shape without the secrets. (2) Something exists on your
machine that is not declared in the repository — a library you installed
manually but never added to requirements, or a file Git is ignoring; the
clean checking computer is the honest one. (3) A server silently running
in the wrong mode is far more dangerous than a server that refuses to
start — fail loudly, fail early. (4) Reviewing your own diff catches real
mistakes, the automatic checks need a Pull Request to guard the merge, and
the habit itself is the professional skill being practiced.*
