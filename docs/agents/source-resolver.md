# Source Resolver

**Pipeline Node:** `source_resolver_node` in `app/pipeline/nodes.py`
**Service:** `app/services/source_resolver_service.py`
**Prompt:** `app/prompts/source_resolver/find_primary_source.txt`

## Purpose

The Source Resolver identifies and links to primary/original sources instead of secondary news outlets. When a TechCrunch article reports on an OpenAI announcement, the resolver attempts to link the newsletter entry to the OpenAI blog post rather than TechCrunch.

## How It Works

The resolver uses a two-stage approach: fast regex extraction first, LLM fallback for what regex misses.

### Stage 1: Regex Extraction

For each extracted article, the `SourceResolverService` scans the content for URLs that match known primary source patterns (official blogs, research paper hosts, GitHub repos, etc.).

- If a primary URL is found, the article's `url` is updated to the primary source and a `source_label` is assigned (e.g., "OpenAI", "arXiv").
- The original URL is preserved in `secondary_source`.

### Stage 2: LLM Fallback

Articles from known secondary sources (e.g., The Verge, TechCrunch, Ars Technica) that weren't resolved by regex are sent to the LLM.

- The LLM receives the article content, original URL, and title.
- It attempts to identify:
  - A `primary_url` — the official source URL mentioned in the article.
  - A `subject_label` — a descriptive label based on who the story is actually about (e.g., "Google DeepMind" instead of "The Verge").
- LLM resolution runs concurrently for all unresolved articles using `asyncio.gather`.
- If the LLM can't find a primary URL but can identify the subject, it applies the label without changing the URL.

### Data Flow

```
Extracted Articles
      ↓
Regex pass → resolved articles (fast)
      ↓
Unresolved secondary sources → LLM fallback (concurrent)
      ↓
All articles with source_label + optional secondary_source
      ↓
Editor Agent
```

### Fields Set

| Field | Description |
|---|---|
| `url` | Updated to primary source if resolved |
| `source_label` | Human-readable label (e.g., "OpenAI", "Meta AI") |
| `secondary_source` | Original URL if the primary URL was different |

### Why This Matters

Without source resolution, the newsletter would attribute stories to news outlets ("via The Verge") rather than the actual subject ("OpenAI"). This improves credibility and gives readers direct links to official announcements, blog posts, and papers.
