# Research Agent — Docker

Dockerized setup for the LangGraph **Research Agent** (Python backend) and its
React **frontend** (Vite). Two containers, one command.

## Prerequisites

- [Docker](https://docs.docker.com/engine/install/) (with Docker Compose — included in Docker Desktop)
- A `.env` file at the project root with your API keys. Copy the template and fill it in:

  ```bash
  cp .env.example .env
  ```

  Required: `OPENROUTER_API_KEY`, `AWS_BEARER_TOKEN_BEDROCK`, `TAVILY_API_KEY`.
  The app will fail at runtime if these are missing.

## Quick start (frontend + API server)

```bash
docker compose up --build
```

Then open:

- Frontend UI: <http://localhost:5173>
- Backend API health check: <http://localhost:8000/health>

The React dev server proxies nothing — it talks to the backend directly at
`http://localhost:8000` (WebSocket at `ws://localhost:8000/ws/{run_id}`), which
is exactly how it runs without Docker, so the UI works unchanged.

## CLI mode (run the graph without the UI)

```bash
docker compose run --rm backend python research_agent/main.py --mode ai --domain fintech
docker compose run --rm backend python research_agent/main.py --mode human --domain elder-care
```

- `--mode ai`: autonomous run, no approval needed.
- `--mode human`: pauses for your approval on stdin (type comma-separated
  opportunity IDs, `all`, or `none`). Needs `docker compose run -it` for the
  interactive prompt:

  ```bash
  docker compose run --rm -it backend python research_agent/main.py --mode human --domain fintech
  ```

- Reports are written to `Result/<topic>/report.md` inside the container,
  which is bind-mounted to `./Result` on your host, so you can read them
  without `docker cp`.

## Useful commands

```bash
docker compose up --build -d   # start in the background
docker compose logs -f         # follow backend + frontend logs
docker compose down            # stop containers
docker compose down -v         # stop and remove containers (and named volumes, if any)
docker compose build --no-cache backend   # force a clean rebuild of the backend
```

## How it's wired

| Piece       | What runs                                        | Port  |
| ----------- | ------------------------------------------------ | ----- |
| `backend`   | `uvicorn research_agent.api.server:app` (FastAPI + WebSocket) | 8000  |
| `frontend`  | Vite dev server (`npm run dev -- --host 0.0.0.0`) | 5173  |

- Backend image: `python:3.12-slim`, installs `research_agent/requirements.txt`.
- Frontend image: `node:22-alpine`, installs via `npm ci` (uses the lockfile).
- Secrets are injected via `env_file: .env` — the `.env` file is **not**
  copied into the images (see `.dockerignore`).

## Notes

- **Volumes**: `./Result` is mounted into the backend container so CLI-mode
  reports land on your host. No other persistent state is kept between
  container restarts (the graph uses an in-memory checkpointer).
- **Rebuild after backend changes**: source is copied into the image at build
  time (no bind mount for code), so after editing backend or frontend code,
  run `docker compose up --build` again.
- **Python version**: the image uses 3.12 even if your local venv is newer —
  langgraph/langchain are best supported there.
