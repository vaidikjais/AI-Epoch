# Testing Guide

## Running Tests

```bash
uv run pytest
```

### Run with verbose output

```bash
uv run pytest -v
```

### Run a specific test file

```bash
uv run pytest app/tests/test_scout_agent.py
```

### Run tests matching a pattern

```bash
uv run pytest -k "test_curator"
```

## Test Structure

Tests are in `app/tests/`:

```
app/tests/
├── conftest.py                # Shared fixtures
├── fixtures/                  # Test data files
├── test_assembler_service.py
├── test_curator_agent.py
├── test_curator_filters.py
├── test_curator_scoring.py
├── test_deduplication.py
├── test_editor_agent.py
├── test_email_service.py
├── test_extract_service.py
├── test_extractor_agent.py
├── test_pipeline_graph.py
├── test_qa_agent.py
├── test_scout_agent.py
└── test_writer_agent.py
```

## Fixtures

Common fixtures are defined in `conftest.py`:

- `mock_db_session` — mocked async SQLAlchemy session
- `make_candidate` — factory for `ArticleCandidate` objects
- `make_article` — factory for `Article` objects

## Writing Tests

### Async tests

Service and pipeline tests are async. Use `@pytest.mark.asyncio`:

```python
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_something(mock_db_session):
    service = SomeService(mock_db_session)
    result = await service.do_thing()
    assert result is not None
```

### Mocking LLM calls

Agent tests mock the LLM to avoid real API calls:

```python
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_agent_scoring(make_candidate):
    with patch.object(CuratorAgent, "_invoke_json", new_callable=AsyncMock) as mock:
        mock.return_value = {"score": 0.85, "reason": "Highly relevant"}
        agent = CuratorAgent()
        result = await agent.score_candidate(candidate_data)
        assert result["score"] == 0.85
```

### Mocking database

Repository calls should be mocked in service tests:

```python
@pytest.mark.asyncio
async def test_service_with_mocked_repo(mock_db_session, make_candidate):
    with patch.object(ArticleCandidateRepository, "get_candidates_by_topic", new_callable=AsyncMock) as mock:
        mock.return_value = [make_candidate(), make_candidate()]
        service = CuratorService(mock_db_session)
        result = await service.curate_candidates("test-topic")
        assert len(result) > 0
```

## Tips

- Always mock external services (LLM, Tavily, SMTP) in tests
- Use `pytest-asyncio` for all async test functions
- Keep test data minimal — use fixture factories
- Run `uv run pytest --tb=short` for concise failure output
