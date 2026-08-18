"""Check every board in the curated list against the live interface.

Run it from the project root:

    python -m scripts.check_boards

For each entry it reports ALIVE (with how many postings) or DEAD (with
the reason). Use it before relying on the list, and whenever ingestion's
source_errors mentions a board — companies change hiring systems, and
this script is how the curated list stays a verified fact instead of a
slowly rotting guess.

(This is a development tool, not part of the web application. It talks to
the real network, so it needs internet access and takes a minute.)
"""

import asyncio

import httpx

from app.ingestion.boards import GREENHOUSE_BOARDS, LEVER_COMPANIES
from app.ingestion.sources import fetch_greenhouse, fetch_lever


async def main() -> None:
    alive = 0
    dead = 0
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for token in GREENHOUSE_BOARDS:
            try:
                postings = await fetch_greenhouse(client, token)
                print(f"ALIVE  greenhouse:{token:<20} {len(postings):>4} postings")
                alive += 1
            except Exception as error:  # noqa: BLE001 — report, don't crash
                print(f"DEAD   greenhouse:{token:<20} {type(error).__name__}: {error}")
                dead += 1
        for company in LEVER_COMPANIES:
            try:
                postings = await fetch_lever(client, company)
                print(f"ALIVE  lever:{company:<25} {len(postings):>4} postings")
                alive += 1
            except Exception as error:  # noqa: BLE001
                print(f"DEAD   lever:{company:<25} {type(error).__name__}: {error}")
                dead += 1
    print(f"\n{alive} alive, {dead} dead.")
    if dead:
        print("Remove or replace the dead entries in app/ingestion/boards.py.")


if __name__ == "__main__":
    asyncio.run(main())
