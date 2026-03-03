# Database Management

## Migrations with Alembic

All schema changes are managed through Alembic. The application does **not** auto-create tables on startup.

### Apply all migrations

```bash
uv run alembic upgrade head
```

### Check current migration version

```bash
uv run alembic current
```

### Create a new migration after model changes

```bash
uv run alembic revision --autogenerate -m "describe your change"
```

Review the generated file in `alembic/versions/` before applying.

### Rollback one migration

```bash
uv run alembic downgrade -1
```

### View migration history

```bash
uv run alembic history
```

## Resetting Data

### Truncate all tables

If PostgreSQL runs in Docker as `newsletter-postgres`:

```bash
docker exec -it newsletter-postgres psql -U postgres -d newsletter \
  -c "TRUNCATE article_candidates, articles, email_groups CASCADE;"
```

`CASCADE` also truncates `email_group_members` via the foreign key.

### Manual SQL reset

```sql
TRUNCATE article_candidates, articles, email_groups CASCADE;
```

## Full Database Reset

Drop and recreate the database, then reapply migrations:

```bash
docker exec -it newsletter-postgres psql -U postgres \
  -c "DROP DATABASE newsletter;" \
  -c "CREATE DATABASE newsletter;"
uv run alembic upgrade head
```

## Tips

- Always run `uv run alembic upgrade head` after pulling new code
- Never modify migration files after they've been applied
- Use `uv run alembic current` to debug migration state issues
