# Architect Agent — A2A server (Research Agent's sibling)
# Build context is the project ROOT, same as the backend (the code uses
# top-level-style sys.path handling, so the whole repo must be visible).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install dependencies first for better layer caching.
COPY research_agent/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the packages the architect needs: its own code plus the shared
# research_agent modules it imports (a2a_schemas, llm clients).
COPY architect_agent/ ./architect_agent/
COPY research_agent/ ./research_agent/
COPY orchestrator/ ./orchestrator/

EXPOSE 8002

# Default: the A2A server consumed by the backend's /design proxy endpoint.
CMD ["python", "-m", "architect_agent.server", "--host", "0.0.0.0", "--port", "8002"]
