# Pipeline Architecture

The newsletter generation pipeline is implemented as a LangGraph `StateGraph` with a `MemorySaver` checkpointer for HITL support.

## Pipeline State

Defined in `app/pipeline/state.py`:

```python
class PipelineState(TypedDict, total=False):
    topic_id: str
    topic_query: str
    max_candidates: int
    recipient_email: Optional[str]
    newsletter_title: Optional[str]
    issue_number: Optional[int]
    scoring_weights: Dict[str, float]

    candidates: List[Any]
    curated: List[Any]
    extracted_articles: List[Dict[str, Any]]
    editor_plan: Optional[Dict[str, Any]]
    newsletter_json: Optional[Dict[str, Any]]
    newsletter_markdown: Optional[str]
    newsletter_html: Optional[str]
    qa_report: Optional[Dict[str, Any]]

    user_feedback: Optional[str]
    curator_feedback: Optional[str]
    qa_revision_feedback: Optional[str]
    qa_revision_count: int

    stages: Dict[str, Any]
    error: Optional[str]
    success: bool
```

## Stages

```
scout → curator → review_articles → extractor → source_resolver → editor → writer → review_newsletter → qa → review_qa → email → END
```

Three HITL checkpoints use `langgraph.types.interrupt()` to pause execution and wait for user input via the `/pipelines/resume` endpoint.

### 1. Scout Node

- `ScoutService` discovers candidates from Tavily, RSS feeds, GitHub Trending, and HF Papers
- Applies keyword pre-filtering and domain-based round-robin to ensure source diversity
- `ScoutAgent` evaluates remaining candidates via LLM (batches of 15)
- Marks approved candidates with `pass_to_extractor=True`

### 2. Curator Node

- `CuratorAgent` scores each candidate's relevance via LLM (batches of 15)
- `CuratorService` computes weighted composite: `0.60 * quality + 0.25 * freshness + 0.15 * provider`
- `CuratorAgent` runs agentic editorial selection (ReAct loop with `read_article` tool) to pick top N
- Falls back to basic selection if the agentic method fails

### 3. Review Articles (HITL)

User reviews curated candidates. Options: **continue**, **re-curate** (with feedback), or **reject**.

### 4. Extractor Node

- Extracts full article content using Trafilatura with Playwright fallback
- Runs up to 4 concurrent extractions with isolated DB sessions
- Stores content in MinIO, metadata in PostgreSQL

### 5. Source Resolver Node

- Regex pass identifies primary source URLs from article content
- LLM fallback resolves remaining secondary sources concurrently
- Sets `source_label` (e.g., "OpenAI" instead of "The Verge") on each article

### 6. Editor Node

- `EditorAgent` plans newsletter structure: headline selection, section assignments, narrative arc

### 7. Writer Node

- `WriterAgent` generates structured newsletter JSON from articles + editor plan
- Post-processing enforces resolved source labels deterministically

### 8. Review Newsletter (HITL)

User reviews the generated newsletter. Options: **approve**, **revise** (with feedback), or **reject**.

### 9. QA Node

- `QAAgent` runs fact-checking (hallucination detection) and quality review
- Produces a combined report with accuracy scores, per-section issues, and quality criteria

### 10. Review QA (HITL)

User reviews the QA report. Options: **approve**, **revise with QA feedback**, **revise with custom feedback**, or **reject**. Revisions loop back to the Writer (max 3 iterations).

### 11. Email Node

- `AssemblerService` renders newsletter JSON into HTML via Jinja2 template
- Sends via SMTP if recipients were specified

## Progress Tracking

Each node emits real-time events via `PipelineProgress`, streamed to the frontend through `GET /pipelines/progress/{topic_id}` (SSE).

## Error Handling

- Conditional edges check for errors and empty outputs at each stage
- Failed nodes capture errors in `state["error"]` and route to END
- LLM calls have built-in retry logic (3 attempts with JSON repair)

## Building the Pipeline

```python
from app.pipeline.graph import build_pipeline

pipeline = build_pipeline(db_session, progress=tracker)
result = await pipeline.ainvoke({
    "topic_id": "ai-healthcare",
    "topic_query": "artificial intelligence in healthcare",
    "max_candidates": 20,
    "recipient_email": "user@example.com",
})
```
