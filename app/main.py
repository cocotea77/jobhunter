"""The web application.

In Step 0 it has exactly one endpoint: /health.

Why start with a health endpoint, of all things? Because everything that
keeps a production service alive talks to it:

- The hosting platform calls it to decide whether the application started
  correctly after a deployment.
- The uptime monitor (added in a later step) calls it every few minutes and
  alerts the operator if it stops answering.
- A human debugging a problem calls it first, to separate "the whole service
  is down" from "one feature is broken".

As the project grows, /health will also report the state of the database,
the freshness of the job data, and whether the daily AI budget is exhausted.
It grows into the single question: "is everything I depend on healthy?"
"""

from fastapi import FastAPI

from app.config import settings

app = FastAPI(title=settings.app_name, version=settings.version)


@app.get("/health")
def health() -> dict:
    """Report that the service is alive, and identify exactly what is running."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
    }
