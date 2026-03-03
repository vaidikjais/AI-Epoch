# Architecture Overview

## System Layers

```
Controller → Service → Repository → Database
                ↓
          Agent (LLM)
```

| Layer        | Responsibility                          | Location            |
|--------------|-----------------------------------------|---------------------|
| Controller   | HTTP routing, request/response handling | `app/controller/`   |
| Schema       | Input validation, output serialization  | `app/schemas/`      |
| Service      | Business logic, orchestration           | `app/services/`     |
| Agent        | LLM-powered reasoning and decisions     | `app/agents/`       |
| Repository   | Database queries                        | `app/repository/`   |
| Model        | Table definitions (SQLModel)            | `app/models/`       |
| Pipeline     | LangGraph state machine                 | `app/pipeline/`     |

## Agents

Each agent wraps an LLM call with a specific responsibility. All agents extend `BaseAgent`, which provides JSON parsing, retry logic, and error handling.

| Agent           | Role                                                    |
|-----------------|---------------------------------------------------------|
| `ScoutAgent`    | Evaluates discovered candidates for topic relevance     |
| `CuratorAgent`  | Scores candidates, then uses a ReAct agent loop to read articles and make editorial picks |
| `ExtractorAgent`| Assesses extracted content quality and recommends strategy |
| `EditorAgent`   | Plans newsletter structure and section organization     |
| `WriterAgent`   | Generates the full newsletter in structured JSON        |
| `QAAgent`       | Fact-checks summaries against sources and reviews quality |

LLM provider is configurable via `LLM_PROVIDER` (default `gemini`). NVIDIA is used when `NVIDIA_API_KEY` is set and `.env` overrides the default. All agents use LangChain for LLM integration.

### Prompt Management

LLM prompts are stored as `.txt` files in `app/prompts/`, organized by agent:

```
app/prompts/
├── scout/           # candidate_assessment, source_evaluation
├── curator/         # relevance_scoring, editorial_selection, editorial_selection_agentic, re_curate_instructions
├── extractor/       # extraction_strategy, content_quality
├── editor/          # structure_planning
├── writer/          # structured_newsletter_system/user, revision_instructions
├── qa/              # quality_review, fact_check
├── source_resolver/ # find_primary_source
└── common/          # json_repair
```

Prompts are loaded at runtime using `load_prompt()` in `app/utils/prompt_loader.py`, which supports `{placeholder}` variable substitution.

## Database

PostgreSQL with four tables, managed by Alembic migrations:

| Table | Purpose |
|---|---|
| `article_candidates` | Discovered URLs — topic, scores, ranks, source metadata |
| `articles` | Extracted article content with MinIO bucket keys |
| `email_groups` | Named recipient groups |
| `email_group_members` | Individual emails within groups (FK to `email_groups`) |

## Controllers

| Controller       | Prefix           | Endpoints |
|------------------|------------------|-----------|
| Pipelines        | `/pipelines`     | Run pipeline, SSE progress |
| Scout            | `/scout`         | Discover candidates, list candidates |
| Curator          | `/curator`       | Score and curate candidates |
| Extractor        | `/extractor`     | Extract single URL or batch candidates |
| Articles         | `/articles`      | CRUD for processed articles |
| Email            | `/email`         | Send newsletter, test SMTP |
| Email Groups     | `/email/groups`  | CRUD for groups and members |
| Admin            | `/admin`         | Health check, metrics |

## Services

| Service                    | What it does                                        |
|----------------------------|-----------------------------------------------------|
| `ScoutService`             | Candidate discovery via Tavily, RSS, GitHub Trending, HF Papers |
| `CuratorService`           | Orchestrates LLM scoring, composite ranking, editorial selection |
| `ArticleService`           | Article ingestion, extraction, and CRUD              |
| `ExtractService`           | Web scraping via Trafilatura + Playwright            |
| `AssemblerService`         | Converts newsletter JSON into Markdown and HTML      |
| `SourceResolverService`    | Identifies primary sources (regex + LLM fallback)    |
| `EmailService`             | Sends newsletters via SMTP                           |
| `EmailGroupService`        | Manages email groups and members                     |
| `AdminService`             | Health checks and metrics                            |

## External Integrations

| Service           | Purpose                          | Config               |
|-------------------|----------------------------------|----------------------|
| NVIDIA AI / Gemini| LLM inference for all agents     | `NVIDIA_API_KEY` / `GEMINI_API_KEY` |
| Tavily            | Web search for article discovery | `TAVILY_API_KEY`     |
| PostgreSQL        | Primary data store               | `DATABASE_URL`       |
| MinIO             | S3-compatible object storage     | `S3_*` env vars      |
| SMTP              | Newsletter email delivery        | `SMTP_*` env vars    |
