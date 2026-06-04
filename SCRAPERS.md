# Scraper Reference

All scrapers must be run from `vedikg-be/` with the virtualenv active:

```bash
cd vedikg-be
source venv/bin/activate
```

A `.env` file with `POSTGRES_URL` is required (copy from `.env.example` if missing).

---

## SB — Śrīmad-Bhāgavatam

**Script:** `scraper_runner.py`  
**Source:** vedabase.io (live scrape)

```bash
# Single canto, all chapters
python scraper_runner.py --canto 2 --chapters all

# Single chapter
python scraper_runner.py --canto 9 --chapters 7

# Multiple chapters (list or range)
python scraper_runner.py --canto 9 --chapters 7,8,9
python scraper_runner.py --canto 9 --chapters 7-9

# Multiple cantos
python scraper_runner.py --canto 1-3 --chapters all

# Quick sample (SB 1.1–5, ~250 verses)
python scraper_runner.py --sample
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--canto` | `1` | Canto(s): `9`, `1-3`, or `1,3,5` |
| `--chapters` | `1` | Chapters: `all`, `7`, `7-9`, or `7,8` |
| `--concurrency` | `5` | Parallel chapter fetches |
| `--sample` | — | Scrape SB 1.1–5 as a quick test |

**Cantos:** 1–12 (19, 10, 33, 31, 26, 19, 15, 24, 24, 90, 31, 13 chapters respectively)

---

## CC — Caitanya-caritāmṛta

**Script:** `cc_scraper_runner.py`  
**Source:** vedabase.io (live scrape)

```bash
# Scrape a full section
python cc_scraper_runner.py --section adi --chapters all
python cc_scraper_runner.py --section madhya --chapters all
python cc_scraper_runner.py --section antya --chapters all

# Specific chapters
python cc_scraper_runner.py --section madhya --chapters 1-5
python cc_scraper_runner.py --section antya --chapters 1
```

**Sections:**

| `--section` | Chapters |
|-------------|----------|
| `adi` | 1–17 |
| `madhya` | 1–25 |
| `antya` | 1–20 |

### CC convenience wrappers

**Sequential** (one chapter at a time, safer for rate limits):
```bash
python cc_scraper_sequential.py
```
Scrapes all three sections in full, sequentially.

**Concurrent** (parallel threads per chapter, faster):
```bash
python cc_scraper_concurrent.py
```
Scrapes all three sections in parallel threads.

---

## CB — Caitanya-bhāgavata

**Script:** `scrape_cb.py` (via `run_cb_scraper.sh`)  
**Source:** Local EPUB files in `epub/`

```bash
bash run_cb_scraper.sh
```

No section/chapter flags — processes all 7 EPUB volumes in one pass. Khaṇḍas: Ādi, Madhya, Antya. Chapter numbers are normalised across volumes automatically.

---

## BRS — Bhakti-rasāmṛta-sindhu

**Script:** `scrape_brs.py`  
**Source:** Local EPUB files in `epub/brs/` (2 volumes, translated by Bhānu Swāmī)

```bash
# All four sections (~1,925 verses total)
python scrape_brs.py

# Single section (1=Eastern, 2=Southern, 3=Western, 4=Northern)
python scrape_brs.py --section 1

# Single wave within a section
python scrape_brs.py --section 1 --wave 1

# Parse only — no DB writes
python scrape_brs.py --dry-run
python scrape_brs.py --section 1 --wave 1 --dry-run

# Delete all BRS data from the DB (clean revert)
python scrape_brs.py --revert
```

**Structure:**

| Section | `--section` | Waves | Description |
|---------|------------|-------|-------------|
| Eastern | `1` | 4 | Types of Bhakti (Sāmānya, Sādhana, Bhāva, Prema) |
| Southern | `2` | 5 | Components of Rasa (Vibhāva, Anubhāva, Sāttvika, Vyabhicāri, Sthāyi) |
| Western | `3` | 5 | Primary Bhakti Rasas (Śānta, Dāsya, Sakhya, Vātsalya, Mādhurya) |
| Northern | `4` | 9 | Secondary Bhakti Rasas (Hāsya, Adbhuta, Vīra, Karuṇa, Raudra, Bhayānaka, Bībhatsa, Maitrī, Rasābhāsa) |

**DB mapping:**
- `Book.code = "BRS"`, each Section → `Canto` (1–4), each Wave → `Chapter`
- Verse text stored in `transliteration` field (IAST romanisation, no Devanāgarī in EPUBs)
- Each commentary stored as a separate `Purport` row with its own `author_id`

**Commentary authors:**
- Jīva Gosvāmī (`slug: jiva-gosvami`)
- Viśvanātha Cakravartī Ṭhākura (`slug: visvanatha-cakravarti-thakura`)

**Note — stale Postgres sequences:** If you hit `UniqueViolation` on `books_pkey` or `authors_pkey`, reset sequences first:
```bash
python -c "
from app.db.base import SessionLocal; import sqlalchemy as sa; db = SessionLocal()
for t in ['books','authors','cantos','chapters','verses','purports']:
    db.execute(sa.text(f\"SELECT setval('{t}_id_seq', COALESCE((SELECT MAX(id) FROM {t}), 1))\"))
db.commit(); db.close(); print('sequences reset')
"
```
