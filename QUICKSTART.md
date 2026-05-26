# SB Viz — Quick Start

## Start Servers

**Backend (FastAPI on port 8000):**
```bash
cd backend
pkill -f uvicorn 2>/dev/null; sleep 1
PYTHONPATH=/Users/anuragsharma/Desktop/sb_viz/backend /Users/anuragsharma/.pyenv/versions/3.11.9/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 > /tmp/api.log 2>&1 &
sleep 2 && curl http://localhost:8000/docs  # Verify running
```

**Frontend (Next.js on port 3000):**
```bash
cd frontend
pkill -f "next dev" 2>/dev/null; sleep 1
npm run dev
# Opens http://localhost:3000
```

---

## Scraping

**Caitanya Bhagavata (full, all 7 volumes):**
```bash
cd backend
rm -f bhagavatam.db bhagavatam.db-shm bhagavatam.db-wal  # Start fresh
PYTHONPATH=/Users/anuragsharma/Desktop/sb_viz/backend /Users/anuragsharma/.pyenv/versions/3.11.9/bin/python scrape_cb.py
```

**Note:** CB scraper automatically:
- Processes all 7 EPUB volumes in sequence
- Applies chapter number offsets to normalize numbering across parts
- Extracts chapter summaries and all verse components
- Stores 11,600 total verses

---

## Database

**Location:** `backend/bhagavatam.db`

**Inspect entities:**
```bash
cd backend && venv/bin/python3 << 'EOF'
from app.db.base import SessionLocal
from app.models.models import Entity, Verse

db = SessionLocal()
print(f"Total entities: {db.query(Entity).count()}")
print(f"Total verses: {db.query(Verse).count()}")

# Find specific entity
e = db.query(Entity).filter(Entity.name.like('%narada%')).first()
if e:
    print(f"  {e.id}: {e.name} ({e.entity_type})")
db.close()
EOF
```

---

## Frontend URLs

**Caitanya Bhagavata:**
- **Home:** `http://localhost:3000/cb`
- **Khanda listing:** `http://localhost:3000/cb/adi`, `/cb/madhya`, `/cb/antya`
- **Chapter listing:** `http://localhost:3000/cb/adi/1` (Chapter 1 of Adi Khanda)
- **Verse detail:** `http://localhost:3000/cb/adi/1/1` (Verse 1 of Chapter 1)

**Srimad Bhagavatam (Other texts):**
- **Home/Verses:** `http://localhost:3000`
- **Characters:** `http://localhost:3000/characters`
- **Places:** `http://localhost:3000/places`
- **Lineage:** `http://localhost:3000/lineage`
- **Graph:** `http://localhost:3000/graph`
- **Character detail:** `http://localhost:3000/characters/23` (Narada)
- **Verse detail:** `http://localhost:3000/sb/9/3/6`

---

## API Endpoints

- `GET /api/entities` — List all entities (supports `?type=person,place,river`)
- `GET /api/entities/{id}` — Entity details
- `GET /api/entities/{id}/relationships` — Family tree (with verse refs)
- `GET /api/entities/{id}/mentions` — Verse mentions
- `GET /api/entities/{id}/graph?depth=N` — BFS graph at depth N
- `GET /api/entities/graph/all` — Full graph (supports `?source=verse|all`)
- `GET /api/entities/relationships/all` — Flat relationship table
- `GET /api/verses/{id}` — Verse with chanda analysis

---

## Useful Tips

**Hard refresh browser:** `Cmd+Shift+R` (Mac) or `Ctrl+Shift+R` (Windows/Linux)

**Watch backend logs:**
```bash
tail -f /tmp/api.log
```

**Kill all servers:**
```bash
lsof -ti:8000,3000 | xargs kill -9 2>/dev/null
```

**DB structure:** See `backend/app/models/models.py`

**Entity counts:** person ~1500, place ~20, river ~3

**Cantos per SB:** 1-19, 2-10, 3-33, 4-31, 5-26, 6-19, 7-15, 8-24, 9-24, 10-90, 11-31, 12-13

PYTHONPATH=/Users/anuragsharma/Desktop/sb_viz/backend /Users/anuragsharma/.pyenv/versions/3.11.9/bin/python /Users/anuragsharma/Desktop/sb_viz/backend/extract_entities.py --book SB --canto 9

# Test with just 10 verses
PYTHONPATH=/Users/anuragsharma/Desktop/sb_viz/backend /Users/anuragsharma/.pyenv/versions/3.11.9/bin/python /Users/anuragsharma/Desktop/sb_viz/backend/extract_entities.py --book SB --canto 9 --limit 10

# Full book
PYTHONPATH=/Users/anuragsharma/Desktop/sb_viz/backend /Users/anuragsharma/.pyenv/versions/3.11.9/bin/python /Users/anuragsharma/Desktop/sb_viz/backend/extract_entities.py --book SB

# All books
PYTHONPATH=/Users/anuragsharma/Desktop/sb_viz/backend /Users/anuragsharma/.pyenv/versions/3.11.9/bin/python /Users/anuragsharma/Desktop/sb_viz/backend/extract_entities.py --all

# Clean tables
sqlite3 /Users/anuragsharma/Desktop/sb_viz/backend/bhagavatam.db "DELETE FROM ai_verse_entities; DELETE FROM ai_relationships; DELETE FROM ai_entities; UPDATE verses SET ai_processed = 0;"


pkill -f uvicorn; sleep 1; cd /Users/anuragsharma/Desktop/sb_viz/backend && /Users/anuragsharma/.pyenv/versions/3.11.9/bin/python -m uvicorn main:app --port 8000 2>&1 &