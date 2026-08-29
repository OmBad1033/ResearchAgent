# Research Agent backend — LangGraph + FastAPI
# Build context is the project ROOT (see docker-compose.yml), so this
# Dockerfile references files via the research_agent/ prefix.

FROM python:3.12-slim

# Stream logs to `docker logs` in real time; keep __pycache__ out of the image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install dependencies first for better layer caching.
COPY research_agent/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend package into /app so `graph.*` and `api.*` resolve as
# top-level modules (the code imports them without the research_agent/ prefix).
COPY research_agent/ ./

EXPOSE 8000

# Default: the Phase 2 API + WebSocket server consumed by the React UI.
# For CLI mode instead, run:
#   docker compose run --rm backend python main.py --mode ai --domain fintech
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
