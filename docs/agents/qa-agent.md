# QA Agent

**File:** `app/agents/qa_agent.py`
**Prompts:** `app/prompts/qa/fact_check.txt`, `app/prompts/qa/quality_review.txt`
**LLM Temperature:** 0.1

## Purpose

The QA Agent is the last validation gate before the newsletter is sent. It runs two independent checks — fact-checking and quality review — and produces a structured report that determines whether the newsletter should be published, revised, or rewritten.

## How It Works

### 1. Fact Check (`fact_check`)

Verifies that newsletter summaries accurately represent the source articles.

- Builds a prompt containing:
  - Every newsletter section (headline, latest_news, company_updates, etc.) with its title, summary, and source URL.
  - The original source articles with their URL, title, and content (first 800 chars).
- The LLM compares each section summary against its source article and returns:
  - `overall_accuracy` (0.0 - 1.0) — average across all sections.
  - Per-section results:
    - `section_type` — e.g., "headline", "news", "company_update"
    - `title` — the specific article title being checked
    - `accuracy_score` (0.0 - 1.0)
    - `issues` — up to 3 specific factual problems (e.g., "Summary claims 'EU passed law' but source says 'EU proposed draft'")
    - `verdict` — `pass`, `warning`, or `fail`

### 2. Quality Review (`quality_review`)

Evaluates overall newsletter quality independent of factual accuracy.

- Sends the full newsletter JSON (minus quality_checks) to the LLM.
- The LLM scores five criteria, each 0.0 - 1.0:
  - `completeness` — are all sections properly filled?
  - `tone_consistency` — is the voice consistent throughout?
  - `summary_quality` — are summaries informative and well-written?
  - `structure` — is the newsletter well-organised?
  - `formatting` — are there formatting issues?
- Returns:
  - `overall_quality` (0.0 - 1.0)
  - `improvements` — up to 5 actionable suggestions
  - `verdict` — `publish`, `review`, or `rewrite`

### Combined Report

The pipeline's `qa_node` combines both results into a single `qa_report`:

```json
{
  "fact_check": { "overall_accuracy": 0.92, "sections": [...] },
  "quality_review": { "overall_quality": 0.85, "criteria": {...}, "improvements": [...], "verdict": "publish" },
  "overall_pass": true
}
```

`overall_pass` is `true` when accuracy >= 0.7 AND quality >= 0.6 AND verdict is not "rewrite".

### HITL Integration

After QA runs, the `review_qa` node pauses the pipeline. The user sees:

- Fact-check accuracy score and per-section issues
- Quality score with criteria breakdown
- Improvement suggestions
- Newsletter preview

The user can:

| Action | Effect |
|---|---|
| **Approve** | Proceed to email delivery |
| **Revise with QA feedback** | Auto-generate feedback from QA issues and loop back to the Writer Agent |
| **Revise with custom feedback** | User writes their own feedback; loops back to Writer Agent |
| **Reject** | Stop the pipeline |

QA revisions are capped at 3 iterations to prevent infinite degradation.

### Data Flow

```
Newsletter JSON + Source Articles
        ↓
QAAgent.fact_check()     → fact_check report
QAAgent.quality_review() → quality_review report
        ↓
Combined qa_report (overall_pass)
        ↓
HITL review_qa → approve / revise / reject
```

### Normalisation & Safety

- Accuracy and quality scores are clamped to [0.0, 1.0].
- Invalid verdicts are derived from scores (e.g., accuracy >= 0.7 → "pass").
- Issues are truncated to 200 characters, capped at 3 per section.
- Improvements are truncated to 200 characters, capped at 5.
