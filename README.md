# AI Epoch

AI-powered newsletter generation system using autonomous LLM agents orchestrated by LangGraph.

## Demo

- https://youtu.be/etfbk0gGlks

## What It Does

Given a topic (e.g. "AI in healthcare"), the system automatically:

1. **Scouts** the web for relevant articles via Tavily, RSS feeds, GitHub Trending, and Hugging Face Papers
2. **Curates** candidates using LLM-based relevance scoring and agentic editorial selection
3. **Extracts** full article content via Trafilatura with Playwright fallback
4. **Resolves** primary sources so the newsletter links to official announcements, not secondary outlets
5. **Edits** the article set into a structured newsletter plan
6. **Writes** a polished newsletter in structured JSON format
7. **QA checks** the output for factual accuracy (hallucination detection) and quality
8. **Emails** the newsletter to individual recipients or email groups via SMTP

Human-in-the-loop (HITL) checkpoints after curation, writing, and QA let you approve, revise, or reject at each stage.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      FastAPI Server                           │
│                                                               │
│  Controllers ─── Services ─── Repositories ─── PostgreSQL    │
│       │                                                       │
│  LangGraph Pipeline (StateGraph + MemorySaver)               │
│                                                               │
│  Scout → Curator → [HITL] → Extractor → Source Resolver      │
│                                    ↓                          │
│  Email ← [HITL] ← QA ← [HITL] ← Writer ← Editor            │
└──────────────────────────────────────────────────────────────┘
         │              │                │
    PostgreSQL     MinIO (S3)      NVIDIA / Gemini LLM
```

## Tech Stack

| Layer       | Technology                                     |
| ----------- | ---------------------------------------------- |
| Framework   | FastAPI + Uvicorn                              |
| Pipeline    | LangGraph (StateGraph + interrupt-based HITL)  |
| LLM         | NVIDIA AI Endpoints / Gemini (LangChain)       |
| ORM         | SQLModel + SQLAlchemy (async)                  |
| Database    | PostgreSQL 15 (via asyncpg)                    |
| Migrations  | Alembic                                        |
| Extraction  | Trafilatura + Playwright + BeautifulSoup       |
| Search      | Tavily API + RSS/Atom feeds + GitHub Trending  |
| Email       | SMTP (aiosmtplib)                              |
| Storage     | MinIO (S3-compatible, for raw article content) |
| Package Mgr | uv                                             |
| Frontend    | Landing page + dashboard (static HTML)         |

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- PostgreSQL (Docker or local)
- NVIDIA API key or Gemini API key

### 1. Clone and install

```bash
git clone <repo-url>
cd agentic-newsletter-mvp
uv sync
```

### 2. Start PostgreSQL

```bash
docker run -d --name newsletter-postgres \
  -e POSTGRES_DB=newsletter \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 postgres:15
```

### 3. Start MinIO (optional)

```bash
docker compose up -d minio
```

### 4. Configure environment

Copy `.env.example` to `.env` and fill in your API keys:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/newsletter
NVIDIA_API_KEY=your-nvidia-api-key
TAVILY_API_KEY=your-tavily-api-key
ENABLE_TAVILY=true
```

### 5. Run migrations

```bash
uv run alembic upgrade head
```

### 6. Start the server

```bash
uv run app/main.py
```

The server runs at `http://localhost:8000`.

- `http://localhost:8000` → Landing page
- `http://localhost:8000/app` → Newsletter dashboard

## Project Structure

```
agentic-newsletter-mvp/
├── app/
│   ├── agents/          # LLM agents (Scout, Curator, Extractor, Editor, Writer, QA)
│   ├── controller/      # FastAPI route handlers
│   ├── core/            # Config, database, search adapters, curator filters
│   ├── models/          # SQLModel database models
│   ├── pipeline/        # LangGraph graph, nodes, state, progress tracking
│   ├── prompts/         # LLM prompt templates (.txt files)
│   ├── repository/      # Database access layer
│   ├── schemas/         # Pydantic request/response schemas
│   ├── services/        # Business logic services
│   ├── templates/       # Jinja2 email templates
│   ├── tests/           # Test suite
│   └── utils/           # Logger, prompt loader, S3 utils
├── alembic/             # Database migration scripts
├── docs/                # Project documentation
├── frontend/            # Landing page (index.html) + dashboard (/app/index.html)
├── scripts/             # Utility scripts
├── docker-compose.yml   # MinIO service
├── pyproject.toml       # Python dependencies (uv)
└── .env                 # Environment variables (not committed)
```

## Database

Four tables managed by Alembic migrations:

| Table                 | Purpose                                                     |
| --------------------- | ----------------------------------------------------------- |
| `article_candidates`  | Discovered URLs before extraction — scores, ranks, metadata |
| `articles`            | Extracted and processed article content                     |
| `email_groups`        | Named groups for batch email delivery                       |
| `email_group_members` | Individual email addresses within groups                    |

## API Overview

| Prefix          | Description                     |
| --------------- | ------------------------------- |
| `/pipelines`    | Run full pipeline, SSE progress |
| `/scout`        | Discover candidates             |
| `/curator`      | Score and curate candidates     |
| `/extractor`    | Extract article content         |
| `/articles`     | CRUD for processed articles     |
| `/email`        | Send newsletters via SMTP       |
| `/email/groups` | Manage email groups and members |
| `/admin`        | Health check and metrics        |
| `/health`       | Simple health endpoint          |

See [docs/api/endpoints.md](docs/api/endpoints.md) for full API reference.

## Documentation

- [API Reference](docs/api/endpoints.md)
- [Architecture Overview](docs/architecture/overview.md)
- [Pipeline Details](docs/architecture/pipeline.md)
- [Quick Start Guide](docs/guides/quick-start.md)
- [Database Management](docs/guides/database-reset.md)
- [Testing Guide](docs/guides/testing.md)

### Agent Documentation

- [Scout Agent](docs/agents/scout-agent.md)
- [Curator Agent](docs/agents/curator-agent.md)
- [Extractor Agent](docs/agents/extractor-agent.md)
- [Editor Agent](docs/agents/editor-agent.md)
- [Writer Agent](docs/agents/writer-agent.md)
- [QA Agent](docs/agents/qa-agent.md)
- [Source Resolver](docs/agents/source-resolver.md)

## License

MIT
