"""The web application.

Step 1 change: the health endpoint now also reports whether the database
is reachable, and its HTTP status code becomes meaningful:

  200 — the application AND its database are working
  503 — the application is alive, but a dependency (the database) is not
        ("503 Service Unavailable" is the standard code for exactly this)

Why the status code matters and not just the text: monitoring tools and
hosting platforms do not read sentences — they read status codes. Railway
decides "did this deployment start correctly?" from the code alone, and an
uptime monitor alerts on any non-200. A health endpoint that answers 200
while its database is down would be lying to every tool that protects us.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import database_status

app = FastAPI(title=settings.app_name, version=settings.version)


@app.get("/health")
async def health() -> JSONResponse:
    """Report whether the service — and everything it depends on — works."""
    database = await database_status()
    healthy = database == "ok"

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "app": settings.app_name,
            "version": settings.version,
            "environment": settings.environment,
            "database": database,
        },
    )
