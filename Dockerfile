FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data directory for SQLite persistence
RUN mkdir -p /app/data

# Setup OpenClaw agent configs (workspaces, SOUL.md, identity)
RUN python scripts/setup_openclaw.py

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Volume mount points:
#   /app/souls   — custom SOUL.md personality files
#   /app/data    — SQLite database persistence
#   /root/.openclaw — OpenClaw gateway config + agent workspaces

# Railway injects $PORT; default to 8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
