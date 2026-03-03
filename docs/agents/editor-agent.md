# Editor Agent

**File:** `app/agents/editor_agent.py`
**Prompts:** `app/prompts/editor/structure_planning.txt`
**LLM Temperature:** 0.3

## Purpose

The Editor Agent acts as a managing editor. Given a set of extracted articles, it creates a structural plan for the newsletter — deciding which article is the headline, how articles are grouped into sections, and what the narrative arc should be.

## How It Works

### Structure Planning (`plan_structure`)

- Receives all extracted articles with their IDs, titles, domains, curation scores, and content previews.
- Sends them to the LLM with instructions to organise them into the newsletter's section taxonomy.
- The LLM returns:
  - `headline_id` — which article to feature as the main headline.
  - `sections` — a list of section assignments, each with a `section` name and `article_ids`.
  - `narrative_arc` — a brief editorial direction (e.g., "Lead with the GPT-5 launch, contrast with open-source alternatives").
  - `editorial_notes` — optional notes for the writer.

### Valid Sections

Articles can be assigned to any of these sections:

| Section | Description |
|---|---|
| `latest_news` | Breaking/recent AI news |
| `company_updates` | Moves by major companies |
| `research_spotlight` | Academic papers and research breakthroughs |
| `tools_and_products` | New tools, libraries, product launches |
| `quick_bytes` | Brief mentions, smaller stories |

### Data Flow

```
Extracted Articles (with resolved sources)
        ↓
EditorAgent.plan_structure()
        ↓
Editor Plan (headline_id, sections, narrative_arc)
        ↓
Writer Agent
```

### Normalisation & Safety

- If the LLM's `headline_id` is not a valid article ID, the article with the highest `curation_score` is used as fallback.
- Each article is assigned to at most one section. Duplicates across sections are prevented.
- Any articles not assigned by the LLM are automatically placed in `quick_bytes` so nothing is silently dropped.
- `narrative_arc` and `editorial_notes` are truncated to 200 and 300 characters respectively.
- If no articles are provided, an empty plan is returned.
