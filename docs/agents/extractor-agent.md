# Extractor Agent

**File:** `app/agents/extractor_agent.py`
**Prompts:** `app/prompts/extractor/extraction_strategy.txt`, `app/prompts/extractor/content_quality.txt`
**LLM Temperature:** 0.2

## Purpose

The Extractor Agent decides *how* to scrape each article and then evaluates *whether* the scraped content is usable. It doesn't do the actual scraping — that's handled by `ExtractorController` using `trafilatura` and `playwright`. The agent provides intelligent strategy selection and quality gating.

## How It Works

### 1. Strategy Planning (`plan_extraction`)

Before scraping a URL, the agent recommends the best extraction approach.

- Input: the article URL and its domain.
- The LLM chooses one of three strategies:
  - `trafilatura` — fast, HTML-only extraction (works for most blogs/news).
  - `playwright` — full browser rendering (needed for SPAs, JS-heavy sites).
  - `trafilatura_then_playwright` — try fast extraction first, fall back to browser if it fails.
- The LLM also predicts `expected_challenges` (e.g., "paywall", "infinite scroll", "cookie consent popup").

### 2. Quality Evaluation (`evaluate_quality`)

After scraping, the agent reviews the extracted text.

- Input: the URL, the extracted text (first 1500 chars), and word count.
- The LLM returns:
  - `quality_score` (0.0 - 1.0)
  - `is_usable` (boolean)
  - `recommendation`: `accept`, `retry_playwright`, or `skip`
  - `issues` — list of problems found (e.g., "mostly navigation text", "content truncated")
- Articles scored below 0.4 are marked as unusable and can be retried with a different strategy or skipped.

### Data Flow

```
Curated Articles
      ↓
ExtractorAgent.plan_extraction()  → strategy per URL
      ↓
ExtractorController (scrape)      → raw text
      ↓
ExtractorAgent.evaluate_quality() → accept / retry / skip
      ↓
Extracted Articles → Source Resolver
```

### Normalisation & Safety

- Strategy defaults to `trafilatura_then_playwright` if the LLM returns an unrecognised value.
- Quality score is clamped to [0.0, 1.0].
- If `is_usable` is not a boolean, it's derived from the score (>= 0.4 = usable).
- Issues and challenges are truncated to 100 characters each, capped at 3 items.
