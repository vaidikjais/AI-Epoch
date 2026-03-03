# Curator Agent

**File:** `app/agents/curator_agent.py`
**Tools:** `app/agents/curator_tools.py` (`read_article`)
**Prompts:** `app/prompts/curator/relevance_scoring.txt`, `app/prompts/curator/editorial_selection.txt`, `app/prompts/curator/editorial_selection_agentic.txt`, `app/prompts/curator/re_curate_instructions.txt`
**LLM Temperature:** Configured via `CURATOR_AGENT_TEMPERATURE` (default 0.2)

## Purpose

The Curator Agent replaces all hardcoded scoring heuristics with LLM-based judgment. It scores every candidate for relevance, then makes an **informed** editorial selection — using a ReAct agent loop that can read full article content before picking.

## How It Works

### 1. Relevance Scoring (`score_relevance`)

Scores each candidate on a 0.0 - 1.0 relevance scale using the LLM.

- Candidates are batched in groups of **15** to prevent output truncation.
- Each candidate's `id`, `title`, `snippet`, and `domain` are sent to the LLM.
- The LLM returns a `relevance_score` and `reasoning` per candidate.
- These scores feed into the composite `curation_score` computed by `CuratorService` (which also factors in freshness and quality).

### 2. Agentic Editorial Selection (`select_editorial_agentic`)

This is a **true ReAct agent** that can read articles before making its final picks.

- Receives ~16 top-scored candidates (2x the requested article count) with titles, snippets, scores, and **URLs**.
- The LLM agent reviews the candidate list, identifies the most promising ~5-8, and uses the `read_article` tool to fetch their full content.
- After reading, it makes an informed editorial decision about which articles form the best newsletter.
- Uses LangGraph's `create_react_agent` with the `read_article` tool.
- Max 12 ReAct iterations prevents runaway tool calls.
- Falls back to the basic (non-agentic) `select_editorial` if the ReAct agent errors out.

### 3. Basic Editorial Selection (`select_editorial`) — Fallback

The non-agentic fallback that picks articles based only on titles/snippets/scores.

- Used automatically if the agentic method fails for any reason.
- Same input/output schema as the agentic version.

### HITL Integration

After curation, a `review_articles` node pauses the pipeline for human review. The user can:

| Action | Effect |
|---|---|
| **Continue** | Proceed to extraction with the current selection |
| **Re-curate** | Send feedback back to the Curator Agent, which re-runs editorial selection with the feedback appended |
| **Reject** | Stop the pipeline entirely |

Re-curation uses `db.merge()` to upsert candidates, avoiding duplicate-key errors on repeated loops.

### Data Flow

```
Filtered Candidates (from Scout)
        ↓
CuratorAgent.score_relevance()           → relevance_score per candidate
        ↓
CuratorService (composite score)         → curation_score = weighted(relevance, freshness, quality)
        ↓
CuratorAgent.select_editorial_agentic()  → ReAct loop: read articles → top N ranked
  └─ fallback: select_editorial()        → basic selection if agent fails
        ↓
HITL review_articles                     → approve / re-curate / reject
```

### Tools

| Tool | Description |
|---|---|
| `read_article(url)` | Fetches full article content via `ExtractService.robust_extract()`. Returns title + first 2000 chars of text. 10s timeout per URL. |

### Normalisation & Safety

- Scores are clamped to [0.0, 1.0].
- If the LLM omits a candidate, a fallback score of 0.5 is used.
- Editorial selections are validated against the actual candidate ID set — unknown IDs are silently dropped.
- Duplicate selections are removed.
- If the LLM returns zero valid selections, a `ValueError` is raised.
- The `read_article` tool has a 10s timeout and returns an error message on failure (doesn't crash the agent).
- Content is capped at 2000 chars per article to keep context window manageable.
- Max 12 ReAct iterations prevents infinite loops.
