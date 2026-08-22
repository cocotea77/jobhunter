# The backend's shipping container (Step 10).
#
# A Dockerfile is a recipe: starting from a known base, install exactly
# what the application needs, copy the code, and declare how to start.
# Railway builds this recipe into an image and runs it; the same recipe
# runs identically on any machine with Docker — that reproducibility is
# the whole point.

FROM python:3.12-slim

# Never buffer logs (we want to see crashes as they happen), never write
# .pyc files (containers are disposable).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first, code second: Docker caches layers, so editing code
# does not reinstall every package on every build.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .
COPY evals ./evals
COPY start.sh .
RUN chmod +x start.sh

# Railway provides $PORT; the start script honors it.
CMD ["./start.sh"]
