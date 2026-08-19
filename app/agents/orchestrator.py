"""The orchestrator: the supervisor above the coach.

Deliberately contains NO AI. It is deterministic code that owns
everything an agent should not be trusted to own about itself:

- validation (empty input, oversized input, unknown candidate)
- session identity (and rejecting cross-candidate session access)
- the wall-clock timeout around the whole turn
- persistence (the transcript, plus per-turn metadata: which tools ran,
  how long the turn took, whether it timed out)

The division of labor is the design: the AGENT decides what to say and
which tools to use; the SUPERVISOR decides whether the conversation may
happen at all, how long it may take, and what history is kept. When an
interviewer asks "what does your orchestrator do?", this docstring is
the answer.

Persistence ordering note (a real bug class): the user's message is
saved AFTER the coach turn returns, because the coach appends the new
message to its working copy itself — persisting first would double it in
the next turn's history.
"""

import asyncio
import time

from sqlalchemy import select

from app.agents.coach import run_coach_turn
from app.config import settings
from app.db import session_factory
from app.models import Candidate, ChatMessage, ChatSession

TIMEOUT_REPLY = (
    "That took longer than my time budget allows, so I stopped rather than "
    "keep you waiting. Fresh matching and tailoring are the slow operations "
    "— try asking for one thing at a time."
)


async def handle_chat(
    candidate_id: int, message: str, session_id: int | None
) -> dict:
    """One complete, supervised chat turn."""
    # --- validation: fail fast, fail kindly -------------------------------
    message = (message or "").strip()
    if not message:
        raise ValueError("message must not be empty")
    if len(message) > settings.chat_max_message_chars:
        raise ValueError(
            f"message too long ({len(message)} characters; "
            f"limit {settings.chat_max_message_chars})"
        )

    async with session_factory() as db:
        if await db.get(Candidate, candidate_id) is None:
            raise LookupError(f"candidate {candidate_id} does not exist")

        # --- session identity ---------------------------------------------
        if session_id is None:
            chat = ChatSession(candidate_id=candidate_id)
            db.add(chat)
            await db.commit()
            await db.refresh(chat)
            session_id = chat.id
        else:
            chat = await db.get(ChatSession, session_id)
            # Wrong candidate gets the SAME answer as "no such session":
            # admitting the session exists would leak another person's data.
            if chat is None or chat.candidate_id != candidate_id:
                raise LookupError(f"session {session_id} not found for this candidate")

        # --- history: user/assistant TEXT only (see coach's memory note) ---
        rows = (
            await db.execute(
                select(ChatMessage.role, ChatMessage.content)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.id)
            )
        ).all()
        history = [{"role": role, "content": content} for role, content in rows]

    # --- the supervised turn ----------------------------------------------
    started = time.perf_counter()
    timed_out = False
    try:
        reply, tools_used = await asyncio.wait_for(
            run_coach_turn(candidate_id, history, message),
            timeout=settings.chat_timeout_seconds,
        )
    except TimeoutError:
        reply, tools_used, timed_out = TIMEOUT_REPLY, [], True
    latency_ms = int((time.perf_counter() - started) * 1000)

    # --- persistence (after the turn — see the ordering note above) -------
    async with session_factory() as db:
        db.add(ChatMessage(session_id=session_id, role="user", content=message))
        db.add(
            ChatMessage(
                session_id=session_id,
                role="assistant",
                content=reply,
                meta={
                    "tools_used": tools_used,
                    "latency_ms": latency_ms,
                    "timed_out": timed_out,
                },
            )
        )
        await db.commit()

    return {
        "session_id": session_id,
        "reply": reply,
        "tools_used": tools_used,
        "latency_ms": latency_ms,
        "timed_out": timed_out,
    }
