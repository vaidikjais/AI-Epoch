# Scout Agent

**File:** `app/agents/scout_agent.py`
**Prompts:** `app/prompts/scout/source_evaluation.txt`, `app/prompts/scout/candidate_assessment.txt`
**LLM Temperature:** 0.2

## Purpose

The Scout Agent is the first LLM-powered step in the pipeline. It evaluates and triages raw article candidates that were discovered by the `ScoutService` (RSS feeds, Tavily search, GitHub trending, Hugging Face papers). Its job is to quickly discard irrelevant noise so downstream agents don't waste tokens on junk.

## How It Works

### 1. Source Evaluation (`evaluate_sources`)

Before any articles are fetched, the Scout Agent ranks the configured seed sources by expected relevance to the current newsletter topic.

- Receives a list of source URLs with their type (RSS, HTML scraper, API, etc.).
- Sends the full list to the LLM with the topic query.
- The LLM returns a `priority_score` (0.0 - 1.0) and a `reasoning` string per source.
- Sources are sorted by priority so higher-value feeds are processed first.

### 2. Candidate Assessment (`assess_candidates`)

After `ScoutService` discovers raw candidates from all sources, the Scout Agent triages them.

- Candidates are processed in **batches of 15** to avoid LLM output truncation.
- Each batch sends the candidate's URL, title, snippet, and domain to the LLM.
- The LLM returns per-candidate:
  - `relevance_score` (0.0 - 1.0)
  - `keep` (boolean) — whether to pass the candidate forward
  - `reasoning` — short justification
- Candidates with `keep=false` are discarded before reaching the Curator Agent.

### Data Flow

```
Seed Sources → ScoutService (fetch) → Raw Candidates
                                          ↓
                              ScoutAgent.assess_candidates()
                                          ↓
                              Filtered Candidates → Curator
```

### Normalisation & Safety

All LLM responses are normalised with strict validation:
- Scores are clamped to [0.0, 1.0].
- If the LLM omits a candidate from its response, a fallback entry is created with `relevance_score=0.5` and `keep=true` to avoid silent data loss.
- Reasoning strings are truncated to 200 characters.
