"""The job sources: where postings come from, and why these sources.

Three public, machine-intended interfaces:

- Greenhouse and Lever are hiring systems ("applicant tracking systems")
  that thousands of real companies use. Both publish every company's
  public job board as JSON at a documented address — intended for exactly
  this kind of reading. One company = one "board token" (its name in the
  address); a curated list of tokens is a curated list of companies.
- Remotive is a remote-jobs aggregator with a public JSON interface.

Why not collect from Indeed or LinkedIn instead? Three reasons worth
saying in an interview. Legally: their terms of service forbid automated
collection. Technically: they detect and block it within days. And
professionally: a hiring manager who sees scraping on a portfolio reads
poor judgment, not initiative. Real companies use licensed feeds and
public interfaces intended for machines — so do we.

Each fetcher below turns one source's answer into the same neutral shape,
RawPosting, so the pipeline never needs to know which source a posting
came from. Adding a fourth source later means adding one fetcher function
and nothing else.
"""

import html as html_entities
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from app.config import settings

# Identify ourselves honestly to the servers we read from — standard
# courtesy for automated clients.
HEADERS = {"User-Agent": "JobHunter (student project; contact via GitHub)"}


class RawPosting(BaseModel):
    """One posting in source-neutral shape — the pipeline's common currency.

    Field names deliberately mirror the jobs table from Step 1: the table
    was designed first (Step 1), and now the data arrives to fit it —
    the professional order.
    """

    source: str
    external_id: str
    company: str
    title: str
    location: str | None
    description: str
    url: str
    posted_at: datetime | None


def html_to_text(html: str) -> str:
    """Job descriptions arrive as HTML (web-page markup). We store clean
    readable text: the AI agents of later steps will read these
    descriptions, and markup is noise to them — noise we would also be
    paying for, since AI reads by the token.

    All whitespace is collapsed to single spaces. Design note from a bug
    this function had: extracting with newline separators splits INLINE
    markup ("Build <b>great</b> systems" became three lines). For text
    whose readers are AI models, evenly collapsed spacing is the robust
    choice — no layout to get wrong."""
    text = BeautifulSoup(html or "", "html.parser").get_text(separator=" ")
    return " ".join(text.split())


async def fetch_greenhouse(client: httpx.AsyncClient, board_token: str) -> list[RawPosting]:
    """One Greenhouse company board, e.g. board_token="stripe".

    Documented public interface:
    https://boards-api.greenhouse.io/v1/boards/<token>/jobs?content=true
    """
    response = await client.get(
        f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs",
        params={"content": "true"},
        headers=HEADERS,
        timeout=settings.ingestion_timeout_seconds,
    )
    response.raise_for_status()  # a bad answer becomes a loud error, not bad data
    postings = []
    for job in response.json().get("jobs", []):
        postings.append(
            RawPosting(
                source="greenhouse",
                external_id=str(job["id"]),
                company=board_token,
                title=job["title"],
                location=(job.get("location") or {}).get("name"),
                # Greenhouse ships descriptions HTML-ESCAPED (&lt;p&gt;
                # instead of <p>) — a real quirk of this source, caught by
                # our recorded-shape test. Unescape first, then strip.
                description=html_to_text(html_entities.unescape(job.get("content", ""))),
                url=job["absolute_url"],
                posted_at=job.get("updated_at"),
            )
        )
    return postings


async def fetch_lever(client: httpx.AsyncClient, company: str) -> list[RawPosting]:
    """One Lever company board, e.g. company="plaid".

    Documented public interface:
    https://api.lever.co/v0/postings/<company>?mode=json
    """
    response = await client.get(
        f"https://api.lever.co/v0/postings/{company}",
        params={"mode": "json"},
        headers=HEADERS,
        timeout=settings.ingestion_timeout_seconds,
    )
    response.raise_for_status()
    postings = []
    for job in response.json():
        # Lever gives time as milliseconds since 1970; convert to a real
        # timestamp (seconds), in UTC, so the database stores an
        # unambiguous moment.
        created_ms = job.get("createdAt")
        posted_at = (
            datetime.fromtimestamp(created_ms / 1000, tz=None).astimezone()
            if created_ms
            else None
        )
        postings.append(
            RawPosting(
                source="lever",
                external_id=str(job["id"]),
                company=company,
                title=job["text"],
                location=(job.get("categories") or {}).get("location"),
                description=html_to_text(job.get("description", "")),
                url=job["hostedUrl"],
                posted_at=posted_at,
            )
        )
    return postings


async def fetch_remotive(client: httpx.AsyncClient, search: str) -> list[RawPosting]:
    """Remotive's public interface, filtered by a search phrase.

    Documented at https://remotive.com/api/remote-jobs?search=...
    """
    response = await client.get(
        "https://remotive.com/api/remote-jobs",
        params={"search": search},
        headers=HEADERS,
        timeout=settings.ingestion_timeout_seconds,
    )
    response.raise_for_status()
    postings = []
    for job in response.json().get("jobs", []):
        postings.append(
            RawPosting(
                source="remotive",
                external_id=str(job["id"]),
                company=job.get("company_name", "unknown"),
                title=job["title"],
                location=job.get("candidate_required_location"),
                description=html_to_text(job.get("description", "")),
                url=job["url"],
                posted_at=job.get("publication_date"),
            )
        )
    return postings
