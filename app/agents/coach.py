"""The coach: a conversational agent that answers by USING TOOLS.

The coach never guesses about the candidate's data — it looks. Asked
"what are my best matches?", it calls list_matches and reads the stored
analyses. Asked to tailor a resume, it invokes the tailoring AGENT as a
tool — a sub-agent behind a tool interface, which is how multi-agent
systems compose without a framework.

Three structural rules, each visible in the code below:

1. LEAST PRIVILEGE BY SHAPE. Every tool receives candidate_id from the
   server-side session — the model's own output cannot name a candidate.
   The model chooses WHICH JOB to discuss; it is structurally unable to
   reach another person's data. Security by code shape beats security by
   prompt instruction.
2. BOUNDED AGENCY. At most coach_max_iterations round trips; the
   orchestrator adds a wall-clock timeout around the whole turn. A loop
   without bounds is a bill without bounds.
3. ERRORS ARE DATA. A tool that fails returns {"error": ...} INTO the
   conversation, so the model can apologize, retry differently, or ask —
   instead of the request crashing with a traceback.
"""

import json

from sqlalchemy import select

from app.agents.tailor import generate_tailored_content
from app.config import settings
from app.db import session_factory
from app.llm import ModelTurn, ToolCall, generate_with_tools
from app.matching import run_matching
from app.models import Candidate, Job, Match, TailoredResume
from app.resume import CandidateProfile

COACH_SYSTEM = """You are a job-search coach for one candidate.

Ground rules: everything you claim about the candidate's matches, scores,
or resumes must come from your tools — never from memory or guesswork. If
a job is not among the candidate's stored matches, say so plainly; do not
invent a score or analysis for it. Tools cost time and money: prefer
list_matches for overviews; use run_matching only when the candidate
explicitly wants fresh matching (it is slow); use tailor_resume only on a
clear request to tailor. Be concise, concrete, and honest about gaps."""

# Model-facing tool descriptions state COST and WHEN-TO-USE — the model
# reads these to decide, so they are prompts, not documentation.
TOOL_SCHEMAS = [
    {
        "name": "list_matches",
        "description": "The candidate's stored job matches, best first, with "
        "scores and analysis. Cheap and fast — the default first move.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_job_details",
        "description": "Full details of ONE job by job_id (from list_matches). "
        "Cheap. Use before discussing a specific posting in depth.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "integer"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "run_matching",
        "description": "Recompute all matches from scratch. SLOW (~30-60s) and "
        "costs money. Only when the candidate explicitly asks for fresh matching.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "tailor_resume",
        "description": "Generate a resume tailored to ONE job (job_id from "
        "list_matches). Slow (~15-45s), costs money, saves the result. Only on "
        "a clear request to tailor.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "integer"}},
            "required": ["job_id"],
        },
    },
]


async def execute_tool(name: str, tool_input: dict, candidate_id: int) -> dict:
    """Run one tool for THIS candidate. Note the signature: candidate_id
    comes from the caller (the session), never from tool_input."""
    if name == "list_matches":
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(Match, Job.title, Job.company)
                    .join(Job, Job.id == Match.job_id)
                    .where(Match.candidate_id == candidate_id)
                    .order_by(
                        Match.llm_score.desc().nulls_last(),
                        Match.vector_score.desc(),
                    )
                    .limit(10)
                )
            ).all()
        return {
            "matches": [
                {
                    "job_id": match.job_id,
                    "title": title,
                    "company": company,
                    "llm_score": match.llm_score,
                    "vector_score": match.vector_score,
                    "analysis": match.analysis,
                }
                for match, title, company in rows
            ]
        }

    if name == "get_job_details":
        async with session_factory() as session:
            job = await session.get(Job, int(tool_input["job_id"]))
        if job is None:
            return {"error": f"job {tool_input['job_id']} does not exist"}
        return {
            "job_id": job.id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "url": job.url,
            "description": job.description[:4000],
        }

    if name == "run_matching":
        return await run_matching(candidate_id)

    if name == "tailor_resume":
        job_id = int(tool_input["job_id"])
        async with session_factory() as session:
            candidate = await session.get(Candidate, candidate_id)
            job = await session.get(Job, job_id)
        if job is None:
            return {"error": f"job {job_id} does not exist"}
        content = await generate_tailored_content(
            CandidateProfile.model_validate(candidate.profile),
            candidate.raw_text,
            job.title,
            job.company,
            job.description,
        )
        async with session_factory() as session:
            row = TailoredResume(
                candidate_id=candidate_id, job_id=job_id,
                content=content.model_dump(),
            )
            session.add(row)
            await session.commit()
        return {"saved": True, "job_id": job_id, "content": content.model_dump()}

    return {"error": f"unknown tool: {name}"}


def plan_fake_turn(
    user_message: str, iteration: int, last_tool_result: dict | None
) -> ModelTurn:
    """Fake mode's scripted coach — deterministic, free, and it drives the
    REAL loop: real tool execution, real persistence, real caps. What is
    canned is only the model's choices; the machinery is live.

    Script: mentions of matches -> look first, then answer from the data.
    A tailoring request -> look, then invoke the tailor sub-agent on the
    top match, then confirm. Anything else -> a plain canned reply.
    """
    lowered = user_message.lower()
    wants_matches = any(word in lowered for word in ("match", "top", "job", "fit"))
    wants_tailor = "tailor" in lowered

    def tool(name: str, tool_input: dict) -> ModelTurn:
        call = ToolCall(id=f"fake_{iteration}_{name}", name=name, input=tool_input)
        return ModelTurn(
            text="",
            tool_calls=[call],
            stop_reason="tool_use",
            raw_content=[
                {"type": "tool_use", "id": call.id, "name": name, "input": tool_input}
            ],
        )

    def reply(text: str) -> ModelTurn:
        return ModelTurn(
            text=text, tool_calls=[], stop_reason="end_turn",
            raw_content=[{"type": "text", "text": text}],
        )

    if iteration == 0 and (wants_matches or wants_tailor):
        return tool("list_matches", {})

    if iteration == 1 and wants_tailor:
        matches = (last_tool_result or {}).get("matches") or []
        if not matches:
            return reply("Fake coach: you have no stored matches yet — run matching first.")
        return tool("tailor_resume", {"job_id": matches[0]["job_id"]})

    if last_tool_result is not None and "matches" in last_tool_result:
        matches = last_tool_result["matches"]
        if not matches:
            return reply("Fake coach: no matches stored yet. Upload a resume and run matching.")
        top = matches[0]
        return reply(
            f"Fake coach: you have {len(matches)} stored matches. The top one is "
            f"{top['title']} at {top['company']} (score {top['llm_score']}). "
            "Real mode reads the analyses and coaches properly."
        )

    if last_tool_result is not None and last_tool_result.get("saved"):
        return reply("Fake coach: tailored resume saved for your top match.")

    return reply(
        "Fake coach: canned reply. Ask about your matches, or switch "
        "FAKE_AI=false for real coaching."
    )


async def run_coach_turn(
    candidate_id: int, history: list[dict], user_message: str
) -> tuple[str, list[str]]:
    """One user message in, one reply out — with a bounded tool loop between.

    Returns (reply_text, tools_used). History is user/assistant TEXT only;
    tool traffic lives and dies inside this turn (replaying stale tool
    payloads bloats context and can contradict fresh data — if the coach
    needs data again next turn, it calls the tool again).
    """
    messages = [*history, {"role": "user", "content": user_message}]
    tools_used: list[str] = []
    last_tool_result: dict | None = None

    for iteration in range(settings.coach_max_iterations):
        turn = await generate_with_tools(
            agent="coach",
            system=COACH_SYSTEM,
            messages=messages,
            tools=TOOL_SCHEMAS,
            fake_response=plan_fake_turn(user_message, iteration, last_tool_result),
        )

        if not turn.tool_calls:
            return turn.text, tools_used

        # The model asked for tools: execute each, feed results back, loop.
        messages.append({"role": "assistant", "content": turn.raw_content})
        results = []
        for call in turn.tool_calls:
            tools_used.append(call.name)
            try:
                output = await execute_tool(call.name, call.input, candidate_id)
            except Exception as error:  # noqa: BLE001 — errors are data, rule 3
                output = {"error": f"{type(error).__name__}: {error}"}
            last_tool_result = output
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(output),
                }
            )
        messages.append({"role": "user", "content": results})

    # Cap reached: end honestly rather than loop forever.
    return (
        "I gathered some information but could not finish reasoning within "
        "my step budget. Here is what I found so far — please ask a more "
        "specific question and I will go straight there.",
        tools_used,
    )
