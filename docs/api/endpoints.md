# API Reference

Base URL: `http://localhost:8000`

---

## Health

### `GET /health`

Simple health check.

**Response:**
```json
{"status": "ok"}
```

---

## Pipelines

### `POST /pipelines/run`

Run the full newsletter generation pipeline.

**Request Body:**
```json
{
  "topic_id": "ai-healthcare",
  "topic_query": "artificial intelligence in healthcare 2026",
  "max_results": 20,
  "recipient_email": "user@example.com"
}
```

| Field             | Type   | Required | Description                         |
|-------------------|--------|----------|-------------------------------------|
| `topic_id`        | string | yes      | Unique topic identifier             |
| `topic_query`     | string | yes      | Search query for article discovery  |
| `max_results`     | int    | no       | Max articles to discover (default 20)|
| `recipient_email` | string | no       | Email to send the final newsletter  |

**Response:** Pipeline execution summary with status, articles found, newsletter generated, and timing.

### `POST /pipelines/resume`

Resume a pipeline after a HITL interrupt with the user's response.

**Request Body:**
```json
{
  "thread_id": "abc-123",
  "user_response": {
    "action": "continue"
  }
}
```

| Field           | Type   | Required | Description                          |
|-----------------|--------|----------|--------------------------------------|
| `thread_id`     | string | yes      | Thread ID returned by the run call   |
| `user_response` | object | yes      | HITL response (action + optional feedback) |

**User response actions by stage:**

| Stage | Actions |
|---|---|
| `review_articles` | `continue`, `re-curate` (with `feedback`), `reject` |
| `review_newsletter` | `approve`, `revise` (with `feedback`), `reject` |
| `review_qa` | `approve`, `revise_with_qa`, `revise` (with `feedback`), `reject` |

**Response:** Pipeline result or next interrupt state.

### `GET /pipelines/progress/{topic_id}`

Server-Sent Events stream for real-time pipeline progress.

**Response:** `text/event-stream` with JSON events:
```
data: {"stage": "scout", "status": "running"}
data: {"stage": "scout", "status": "done", "detail": {...}}
data: {"stage": "curator", "status": "running"}
...
data: {"stage": "__done__"}
```

---

## Scout

### `POST /scout/discover`

Discover article candidates for a topic.

**Request Body:**
```json
{
  "topic_id": "ai-healthcare",
  "topic_query": "artificial intelligence in healthcare 2026",
  "max_results": 20
}
```

**Response:** List of discovered candidates with URLs, titles, snippets, and source providers.

### `GET /scout/candidates`

List stored candidates, optionally filtered by topic.

**Query Parameters:**

| Param      | Type   | Description              |
|------------|--------|--------------------------|
| `topic_id` | string | Filter by topic ID       |
| `limit`    | int    | Max results (default 50) |
| `offset`   | int    | Pagination offset        |

**Response:** Array of `ArticleCandidateOut` objects.

---

## Curator

### `POST /curator/curate`

Score and rank candidates for a topic using LLM-based evaluation.

**Request Body:**
```json
{
  "topic_id": "ai-healthcare",
  "max_candidates": 8
}
```

**Response:** Curated candidates ranked by composite score (quality + freshness + relevance).

---

## Extractor

### `POST /extractor/extract`

Extract full content from a single URL.

**Request Body:**
```json
{
  "url": "https://example.com/article"
}
```

**Response:** Extracted article with title, content, and metadata.

### `POST /extractor/extract-candidates`

Extract content from multiple approved candidates.

**Request Body:**
```json
{
  "topic_id": "ai-healthcare",
  "limit": 10
}
```

**Response:** Batch extraction results with success/failure counts.

---

## Articles

### `POST /articles`

Create an article record manually.

**Request Body:**
```json
{
  "url": "https://example.com/article",
  "title": "Article Title",
  "source": "example.com"
}
```

### `GET /articles`

List all articles.

**Query Parameters:**

| Param    | Type   | Description              |
|----------|--------|--------------------------|
| `status` | string | Filter by status         |
| `limit`  | int    | Max results (default 50) |
| `offset` | int    | Pagination offset        |

**Response:** Array of `ArticleOut` objects.

### `GET /articles/{article_id}`

Get a single article by ID.

### `GET /articles/{article_id}/content`

Get the raw extracted content of an article as plain text.

---

## Email Groups

### `GET /email/groups`

List all email groups.

**Response:** Array of `GroupResponse` objects with id, name, description, member_count, created_at.

### `POST /email/groups`

Create a new email group.

**Request Body:**
```json
{
  "name": "Tech Readers",
  "description": "Subscribers interested in tech news"
}
```

**Response:** `GroupResponse` (201 Created).

### `GET /email/groups/{id}`

Get group details including members.

**Response:** `GroupDetailResponse` with id, name, description, members array.

### `PUT /email/groups/{id}`

Update group name and description.

**Request Body:**
```json
{
  "name": "Updated Name",
  "description": "Updated description"
}
```

**Response:** `GroupResponse`.

### `DELETE /email/groups/{id}`

Delete a group and its members. Returns 204 No Content.

### `POST /email/groups/{id}/members`

Add members to a group.

**Request Body:**
```json
{
  "emails": ["user@example.com", "other@example.com"]
}
```

**Response:** Array of `MemberResponse` (201 Created).

### `DELETE /email/groups/{id}/members/{member_id}`

Remove a member from a group. Returns 204 No Content.

---

## Email

### `POST /email/send`

Send a newsletter via SMTP.

**Request Body:**
```json
{
  "recipient_email": "user@example.com",
  "subject": "Newsletter #42",
  "html_body": "<html>...</html>"
}
```

### `POST /email/test`

Send a test email to verify SMTP configuration.

**Request Body:**
```json
{
  "recipient_email": "user@example.com"
}
```

---

## Admin

### `GET /admin/health`

Detailed health check with database connectivity status.

**Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "timestamp": "2026-02-12T10:00:00Z"
}
```

### `GET /admin/metrics`

Application metrics including article and candidate counts.

**Response:**
```json
{
  "total_articles": 15,
  "total_candidates": 200,
  "articles_by_status": {"ingested": 10, "extracted": 5}
}
```
