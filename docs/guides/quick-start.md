# Quick Start Guide

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (for PostgreSQL and MinIO)
- NVIDIA API key or Gemini API key (for LLM agents)
- Tavily API key (optional, for web search)

## 1. Install dependencies

```bash
cd agentic-newsletter-mvp
uv sync
```

This installs all dependencies defined in `pyproject.toml` into a local `.venv`.

## 2. Start PostgreSQL

If you already have a PostgreSQL instance, create a database called `newsletter`. Otherwise, start one via Docker:

```bash
docker run -d --name newsletter-postgres \
  -e POSTGRES_DB=newsletter \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 postgres:15
```

## 3. Start MinIO (optional)

```bash
docker compose up -d minio
```

MinIO stores raw extracted article content. The pipeline works without it but won't persist raw HTML/text.

## 4. Configure environment

Create a `.env` file from the example:

```bash
cp .env.example .env
```

Fill in your API keys. At minimum:

```env
NVIDIA_API_KEY=nvapi-xxxx
TAVILY_API_KEY=tvly-xxxx
ENABLE_TAVILY=true
```

For SMTP (real email delivery):

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASSWORD=app-password
SMTP_FROM=your@email.com
SMTP_TLS=true
```

## 5. Run database migrations

```bash
uv run alembic upgrade head
```

## 6. Start the server

```bash
uv run app/main.py
```

The server starts at `http://localhost:8000`.

## 7. Open the app

Navigate to `http://localhost:8000` in your browser to view the landing page.

Click **Generate Newsletter** (or open `http://localhost:8000/app`) to access the pipeline dashboard. The dashboard lets you:

- Enter a topic and run the full pipeline
- See real-time progress via the step tracker
- Review and approve articles at HITL checkpoints
- View the generated newsletter with QA metrics
- Send the newsletter to individuals or email groups

## 8. Run a pipeline via API

```bash
curl -X POST http://localhost:8000/pipelines/run \
  -H "Content-Type: application/json" \
  -d '{
    "topic_id": "ai-healthcare",
    "topic_query": "artificial intelligence in healthcare 2026",
    "max_results": 20
  }'
```

## 9. Use individual endpoints

Each pipeline stage can be called independently:

```bash
# Discover candidates
curl -X POST http://localhost:8000/scout/discover \
  -H "Content-Type: application/json" \
  -d '{"topic_id": "ai-healthcare", "topic_query": "AI healthcare 2026"}'

# Curate candidates
curl -X POST http://localhost:8000/curator/curate \
  -H "Content-Type: application/json" \
  -d '{"topic_id": "ai-healthcare", "max_candidates": 8}'

# Extract content from candidates
curl -X POST http://localhost:8000/extractor/extract-candidates \
  -H "Content-Type: application/json" \
  -d '{"topic_id": "ai-healthcare", "limit": 10}'
```

## Troubleshooting

**Port already in use:**

```bash
lsof -ti:8000 | xargs kill -9
```

**Database connection errors:**

- Verify PostgreSQL is running: `docker ps`
- Check `DATABASE_URL` in `.env` matches your setup

**LLM errors:**

- Verify your API key is valid (`NVIDIA_API_KEY` or `GEMINI_API_KEY`)
- Check NVIDIA API status at https://build.nvidia.com

**No candidates found:**

- Ensure `ENABLE_TAVILY=true` and `TAVILY_API_KEY` is set
- Try a broader search query
