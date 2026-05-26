# PostgreSQL Migration Guide

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create `.env` file with PostgreSQL connection:**
   ```
   POSTGRES_URL=postgresql://postgres:[PASSWORD]@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres
   GEMINI_API_KEY=your_key_here
   ```

## Running Migrations

### Apply all pending migrations:
```bash
python migrate.py
```

This will:
- Create `schema_migrations` table (if not exists)
- Check which migrations have been applied
- Run any pending migrations automatically

### Manual migration execution:

**Upgrade (apply migrations):**
```bash
python migrate.py
```

**To reverse a migration** (downgrade), you'd need to edit migrate.py to support the `downgrade` function. Currently it only supports upgrade.

## Migration Files

Migrations are in `backend/migrations/` directory:

- `001_initial_schema.py` - Creates base tables (books, chapters, verses, etc.)
- `002_ai_tables.py` - Creates AI-specific tables (ai_entities, ai_relationships, ai_verse_entities)

Each migration file has:
- `upgrade(conn)` - Apply the migration
- `downgrade(conn)` - Revert the migration

## Database Schema

### Base Tables
- `books` - Book metadata (SB, CC, CB)
- `cantos` - Cantos within books
- `chapters` - Chapters within cantos
- `verses` - Individual verses with text, translation, purport
- `authors` - Purport authors
- `purports` - Purport content
- `scrape_jobs` - Tracking scraping jobs

### AI Tables (NEW)
- `ai_entities` - Extracted entities from AI
- `ai_relationships` - Relationships between entities
- `ai_verse_entities` - Linking verses to entities

## API Endpoints

All API endpoints now use PostgreSQL via psycopg3:

- `GET /api/ai/entities` - List AI entities
- `GET /api/ai/entities/{id}` - Get entity detail
- `GET /api/ai/relationships` - List relationships
- `GET /api/ai/graph` - Force graph data
- `GET /api/ai/progress` - Extraction progress

## Notes

- All timestamps use PostgreSQL's `CURRENT_TIMESTAMP`
- Foreign keys are properly enforced
- Indexes created for common queries
- Connection pooling handled automatically by psycopg3
