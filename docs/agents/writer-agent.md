# Writer Agent

**File:** `app/agents/writer_agent.py`
**Prompts:** `app/prompts/writer/structured_newsletter_system.txt`, `app/prompts/writer/structured_newsletter_user.txt`, `app/prompts/writer/revision_instructions.txt`
**LLM Temperature:** 0.4

## Purpose

The Writer Agent is responsible for generating the full newsletter content as structured JSON. It takes the extracted articles and editor plan and produces detailed, information-dense summaries for each section. It also handles revisions when feedback comes from HITL or the QA Agent.

## How It Works

### 1. Initial Generation (`write_newsletter`)

- Builds an `articles_block` JSON containing each article's ID, title, domain, URL, resolved source label, curation score, and up to 3000 characters of content preview.
- Includes the editor's section hint (e.g., "HEADLINE", "LATEST_NEWS", "QUICK_BYTES") for each article.
- Sends this to the LLM along with the issue number and date.
- The LLM returns structured JSON matching the newsletter schema (headline, latest_news, company_updates, research_spotlight, tools_and_products, quick_bytes, etc.).

### 2. Revision (`revise_newsletter`)

When HITL feedback or QA feedback triggers a revision:

- The LLM receives three pieces of context:
  1. **Editor feedback** — the specific changes requested.
  2. **Original source articles** — the ground truth content (up to 3000 chars each), so the LLM doesn't hallucinate from its own previous output.
  3. **Previous draft** — the newsletter JSON being revised, for reference only.
- Explicit grounding rules in the prompt prevent fact drift:
  - "Every claim MUST be verifiable against the ORIGINAL SOURCE ARTICLES."
  - "DO NOT copy errors from the previous draft."

### 3. Source Label Enforcement

After the Writer Agent generates or revises the newsletter, the pipeline applies a deterministic `_override_source_labels` post-processing step that forces the resolved `source_label` and `url` from the original articles onto the newsletter JSON. This prevents the LLM from reverting to secondary news outlet names.

### HITL Integration

The Writer Agent participates in two feedback loops:

| Trigger | Source | What Happens |
|---|---|---|
| `review_newsletter` | Human editor | User provides custom feedback; writer revises |
| `review_qa` | QA Agent or human | QA issues are formatted into feedback; writer revises with source articles grounded |

A **max of 3 QA revisions** is enforced at the graph level to prevent infinite degradation loops.

### Data Flow

```
Extracted Articles + Editor Plan
        ↓
WriterAgent.write_newsletter()
        ↓
Newsletter JSON → _override_source_labels()
        ↓
AssemblerService → Markdown + HTML
        ↓
HITL review_newsletter → approve / revise → (loop back to writer)
        ↓
QA Agent → review_qa → approve / revise → (loop back to writer, max 3x)
```

### Output Schema

The normalised newsletter JSON contains:

```
issue_title, issue_number, date_iso, subheadline, intro,
headline: {title, summary, source_label, source_url},
latest_news: [{title, summary, source_label, source_url}, ...],
company_updates: [...],
research_spotlight: {title, summary, source_label, source_url},
tools_and_products: [...],
open_source_spotlight: [...],
quick_bytes: [...],
wrap, footer, total_articles, estimated_read_time, quality_checks
```

### Normalisation & Safety

- If the LLM returns a string instead of a dict for `headline` or `research_spotlight`, it's auto-wrapped.
- List sections are filtered to ensure only valid dict entries pass through.
- The `_empty_newsletter` fallback is returned when no articles are provided.
