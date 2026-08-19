"""The AI gateway: the single door through which every AI call passes.

THE ONE RULE OF THIS PROJECT: no other module ever calls the AI service
directly. Everything goes through the two functions in this file:

    generate_text(...)        -> a plain text answer
    generate_structured(...)  -> an answer validated against an exact shape

Why one door, and why it is the most important design decision here:

1. MEASUREMENT. Every call — every agent, forever — is recorded in the
   agent_runs table: who called, which model, how long it took, how many
   tokens, how much money, success or failure. Because there is one door,
   nothing can go unmeasured. The /metrics endpoint, the cost dashboard,
   and the evaluation harness (Step 6) all read these records.
2. CONTROL. The emergency spending stop (Step 8) will be a few lines
   inside this one file — and it will govern every agent automatically,
   including agents that have not been written yet.
3. HONESTY. Structured answers are validated against a declared shape;
   a malformed answer gets exactly one retry, then fails loudly. Bad data
   never flows silently onward.

Fake mode (settings.fake_ai, True by default): the gateway returns the
caller's declared realistic example instead of calling the real service.
Zero cost, no key, works offline — students and Continuous Integration
never spend a cent. The caller provides the fake answer because the caller
knows what a realistic answer looks like; this habit later becomes the
golden examples of the evaluation harness.
"""

import json
import time

from anthropic import AsyncAnthropic
from pydantic import BaseModel
from sqlalchemy import insert

from app.config import settings
from app.db import session_factory
from app.models import AgentRun

# What one million tokens cost, in US dollars: (input price, output price).
# These numbers change over time — check the provider's pricing page when
# you change models. "fake" is free by definition.
PRICES_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "text-embedding-3-small": (0.02, 0.00),  # embeddings: input only
    "fake": (0.00, 0.00),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Turn a call's token counts into dollars, using the price table.

    Unknown models are priced at the most expensive known rate — when in
    doubt, overestimate cost rather than underestimate it.
    """
    default = max(PRICES_PER_MILLION_TOKENS.values())
    input_price, output_price = PRICES_PER_MILLION_TOKENS.get(model, default)
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


async def record_run(
    *,
    agent: str,
    model: str,
    latency_ms: int,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    success: bool,
    error: str | None,
) -> None:
    """Write one row to agent_runs: the permanent record of one round trip.

    Deliberate design choice: if this write fails (for example, the
    database is briefly unreachable), we print a warning and carry on —
    we do NOT crash the user's request. Measurement must never break the
    product it measures. The health endpoint already tells the operator
    when the database is down; losing a metrics row is the lesser harm.
    """
    try:
        async with session_factory() as session:
            await session.execute(
                insert(AgentRun).values(
                    agent=agent,
                    model=model,
                    latency_ms=latency_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    success=success,
                    error=error,
                )
            )
            await session.commit()
    except Exception as recording_error:  # noqa: BLE001 — by design, see above
        print(f"WARNING: could not record agent run: {recording_error!r}")


async def _call_real_model(
    system: str, prompt: str, max_tokens: int
) -> tuple[str, int, int]:
    """The only lines in the whole project that talk to the real AI service.

    Returns (answer text, input tokens, output tokens).
    """
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.ai_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return (
        response.content[0].text,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )


async def _one_round_trip(
    *, agent: str, system: str, prompt: str, max_tokens: int, fake_response: str
) -> str:
    """One measured round trip to the model (real or fake).

    Everything is timed and recorded — including failures, which are
    recorded with success=False and then re-raised. A failure you cannot
    see in the records is a failure you cannot fix.
    """
    started = time.perf_counter()
    model = "fake" if settings.fake_ai else settings.ai_model

    try:
        if settings.fake_ai:
            answer = fake_response
            # Rough token estimate (about 4 characters per token) so that
            # fake-mode metrics have realistic-looking shapes to display.
            input_tokens = (len(system) + len(prompt)) // 4
            output_tokens = len(answer) // 4
        else:
            answer, input_tokens, output_tokens = await _call_real_model(
                system, prompt, max_tokens
            )
    except Exception as error:
        latency_ms = int((time.perf_counter() - started) * 1000)
        await record_run(
            agent=agent,
            model=model,
            latency_ms=latency_ms,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            success=False,
            error=f"{type(error).__name__}: {error}",
        )
        raise

    latency_ms = int((time.perf_counter() - started) * 1000)
    await record_run(
        agent=agent,
        model=model,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=estimate_cost_usd(model, input_tokens, output_tokens),
        success=True,
        error=None,
    )
    return answer


async def generate_text(
    *,
    agent: str,
    prompt: str,
    system: str = "",
    max_tokens: int | None = None,
    fake_response: str,
) -> str:
    """Ask the model for a plain text answer.

    agent: a short name for who is asking ("resume_parser", "coach", ...).
        It becomes the label in agent_runs and /metrics — choose it well.
    fake_response: the realistic answer fake mode returns. Required, and
        keyword-only, so no call site can forget that fake mode exists.
    """
    max_tokens = min(max_tokens or settings.ai_max_output_tokens,
                     settings.ai_max_output_tokens)
    return await _one_round_trip(
        agent=agent,
        system=system,
        prompt=prompt,
        max_tokens=max_tokens,
        fake_response=fake_response,
    )


def _strip_code_fences(text: str) -> str:
    """Models sometimes wrap JSON in ```json ... ``` decoration.
    Remove it before parsing; the content is what matters."""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n") if "\n" in text else len(text)
        text = text[first_newline + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


async def generate_structured[SchemaT: BaseModel](
    *,
    agent: str,
    prompt: str,
    schema: type[SchemaT],
    system: str = "",
    max_tokens: int | None = None,
    fake_response: dict,
) -> SchemaT:
    """Ask the model for an answer in an exact shape, and enforce it.

    The shape is a Pydantic class (the same technique as our Settings).
    The model is told the exact fields to produce; its answer is parsed
    and validated. A malformed answer gets exactly ONE retry, with the
    error message included so the model can correct itself. A second
    failure raises loudly. This retry-once-then-fail policy is a
    project-wide contract: agents either return valid data or fail
    visibly — never silently pass garbage onward.
    """
    schema_description = json.dumps(schema.model_json_schema(), indent=2)
    full_system = (
        (system + "\n\n" if system else "")
        + "Answer with a single JSON object matching this exact schema — "
        + "no prose before or after it:\n"
        + schema_description
    )

    text = await _one_round_trip(
        agent=agent,
        system=full_system,
        prompt=prompt,
        max_tokens=max_tokens or settings.ai_max_output_tokens,
        fake_response=json.dumps(fake_response),
    )
    try:
        return schema.model_validate(json.loads(_strip_code_fences(text)))
    except Exception as first_error:
        retry_prompt = (
            prompt
            + "\n\nYour previous answer could not be used. The problem was: "
            + f"{first_error}\nAnswer again with ONLY the JSON object."
        )
        text = await _one_round_trip(
            agent=agent,
            system=full_system,
            prompt=retry_prompt,
            max_tokens=max_tokens or settings.ai_max_output_tokens,
            fake_response=json.dumps(fake_response),
        )
        try:
            return schema.model_validate(json.loads(_strip_code_fences(text)))
        except Exception as second_error:
            raise RuntimeError(
                f"Agent '{agent}' produced invalid structured output twice. "
                f"Last error: {second_error}"
            ) from second_error


class ToolCall(BaseModel):
    """One tool request from the model: which tool, with what input."""

    id: str
    name: str
    input: dict


class ModelTurn(BaseModel):
    """One round trip's normalized result, for tool-using agents.

    raw_content preserves the model's answer blocks exactly, because the
    conversation protocol requires echoing them back verbatim when
    returning tool results — the model's memory of its own requests.
    """

    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    raw_content: list[dict]


async def generate_with_tools(
    *,
    agent: str,
    system: str,
    messages: list[dict],
    tools: list[dict],
    max_tokens: int | None = None,
    fake_response: ModelTurn,
) -> ModelTurn:
    """One round trip of a TOOL-USING conversation — the third and last
    door in the gateway (text, structured, and now tools).

    Unlike the one-shot doors, the caller owns the loop: it executes the
    requested tools, appends the results to `messages`, and calls again.
    The gateway's jurisdiction is unchanged — every round trip measured
    and recorded, fake mode honored (the caller scripts the fake turn,
    because only the caller knows its conversation state).
    """
    started = time.perf_counter()
    model = "fake" if settings.fake_ai else settings.ai_model

    try:
        if settings.fake_ai:
            turn = fake_response
            input_tokens = sum(len(str(m.get("content", ""))) for m in messages) // 4
            output_tokens = len(turn.text) // 4 + 32 * len(turn.tool_calls)
        else:
            client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            response = await client.messages.create(
                model=settings.ai_model,
                max_tokens=min(
                    max_tokens or settings.ai_max_output_tokens,
                    settings.ai_max_output_tokens,
                ),
                system=system,
                messages=messages,
                tools=tools,
            )
            text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            tool_calls = [
                ToolCall(id=block.id, name=block.name, input=block.input)
                for block in response.content
                if block.type == "tool_use"
            ]
            raw_content = [block.model_dump() for block in response.content]
            turn = ModelTurn(
                text=text,
                tool_calls=tool_calls,
                stop_reason=response.stop_reason or "end_turn",
                raw_content=raw_content,
            )
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
    except Exception as error:
        await record_run(
            agent=agent,
            model=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            success=False,
            error=f"{type(error).__name__}: {error}",
        )
        raise

    await record_run(
        agent=agent,
        model=model,
        latency_ms=int((time.perf_counter() - started) * 1000),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=estimate_cost_usd(model, input_tokens, output_tokens),
        success=True,
        error=None,
    )
    return turn
