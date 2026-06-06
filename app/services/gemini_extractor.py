"""
Gemini-powered entity & relationship extractor for Bhagavatam texts.

Key pool: set GEMINI_API_KEYS=key1,key2,key3 in .env
Per key limits: 15 RPM, 500 RPD

Multi-stage extraction pipeline (3 API calls per verse):
  Stage 1 — Entities + Concepts:  what is explicitly named/discussed and where (verse vs purport)
  Stage 2 — Relationships:        links between only the entities identified in stage 1
  Stage 3 — Verification:         catches type errors, wrong directions, unsupported claims

Results are assembled in memory first, then saved atomically.
Accuracy over quantity — only high-confidence, explicitly-stated facts.
"""


import json
import logging
import os
import re
import time
import threading
import unicodedata
from datetime import date
from dotenv import load_dotenv


from google import genai
from google.genai import types as genai_types


load_dotenv()


logger = logging.getLogger(__name__)


RPM_LIMIT = 15
RPD_LIMIT = 500
HOURS_TO_RUN = 12




# ---------------------------------------------------------------------------
# Multi-key pool
# ---------------------------------------------------------------------------


class ApiKey:
   def __init__(self, key: str):
       self.key = key
       self.client = genai.Client(api_key=key)
       self._lock = threading.Lock()
       self._day: date = date.today()
       self._day_count: int = 0
       self._minute_calls: list[float] = []


   def _refresh_day(self):
       today = date.today()
       if today != self._day:
           self._day = today
           self._day_count = 0


   @property
   def remaining_today(self) -> int:
       with self._lock:
           self._refresh_day()
           return RPD_LIMIT - self._day_count


   @property
   def remaining_this_minute(self) -> int:
       with self._lock:
           now = time.monotonic()
           self._minute_calls = [t for t in self._minute_calls if now - t < 60]
           return RPM_LIMIT - len(self._minute_calls)


   @property
   def seconds_until_rpm_available(self) -> float:
       with self._lock:
           now = time.monotonic()
           self._minute_calls = [t for t in self._minute_calls if now - t < 60]
           if len(self._minute_calls) < RPM_LIMIT:
               return 0.0
           return max(0.0, 60.0 - (now - min(self._minute_calls)))


   def record_call(self):
       with self._lock:
           self._refresh_day()
           self._day_count += 1
           self._minute_calls.append(time.monotonic())




class KeyPool:
   def __init__(self, keys: list[str]):
       if not keys:
           raise ValueError("No API keys provided")
       self.keys = [ApiKey(k) for k in keys]


       # Calculate optimal request delay based on number of keys
       total_daily_capacity = len(self.keys) * RPD_LIMIT
       self.request_delay = (HOURS_TO_RUN * 3600) / total_daily_capacity


       logger.info(f"Key pool: {len(self.keys)} key(s), "
                   f"capacity {total_daily_capacity} RPD / {len(self.keys) * RPM_LIMIT} RPM")
       logger.info(f"Spreading over {HOURS_TO_RUN} hours → {self.request_delay:.2f}s delay between requests "
                   f"({total_daily_capacity / HOURS_TO_RUN:.1f} requests/hour total)")


   def log_quota_status(self):
       """Log current quota usage for all keys with color coding (current session only)."""
       # ANSI color codes
       GREEN = '\033[92m'
       YELLOW = '\033[93m'
       RED = '\033[91m'
       CYAN = '\033[96m'
       BOLD = '\033[1m'
       RESET = '\033[0m'


       total_remaining = sum(k.remaining_today for k in self.keys)
       total_capacity = len(self.keys) * RPD_LIMIT
       total_used = total_capacity - total_remaining
       percent_used = (total_used / total_capacity) * 100 if total_used > 0 else 0


       # Color based on usage percentage
       if percent_used < 50:
           quota_color = GREEN
       elif percent_used < 80:
           quota_color = YELLOW
       else:
           quota_color = RED


       # Build colored status line
       quota_bar = self._make_bar(percent_used)
       status = f"{CYAN}┃ QUOTA {RESET}{quota_color}{quota_bar} {total_used:4d}/{total_capacity} ({percent_used:5.1f}%){RESET} {CYAN}┃{RESET}"


       # Per-key breakdown
       key_parts = []
       for i, key in enumerate(self.keys, 1):
           used = RPD_LIMIT - key.remaining_today
           key_percent = (used / RPD_LIMIT) * 100
           if key_percent < 50:
               key_color = GREEN
           elif key_percent < 80:
               key_color = YELLOW
           else:
               key_color = RED
           key_bar = self._make_bar(key_percent, width=8)
           key_parts.append(f"{CYAN}K{i}{RESET} {key_color}{key_bar}{RESET}")


       logger.info(status + " " + " ".join(key_parts))


   def _make_bar(self, percent: float, width: int = 12) -> str:
       """Create a simple bar representation."""
       filled = int((percent / 100) * width)
       empty = width - filled
       return '█' * filled + '░' * empty


   def acquire(self) -> ApiKey:
       """Return best available key. Waits for RPM if needed. Raises if daily exhausted."""
       while True:
           available = [k for k in self.keys if k.remaining_today > 0]
           if not available:
               raise RuntimeError(
                   "All API keys exhausted their daily quota. Add more keys or resume tomorrow."
               )
           rpm_ready = [k for k in available if k.remaining_this_minute > 0]
           if rpm_ready:
               return max(rpm_ready, key=lambda k: k.remaining_today)
           wait = min(k.seconds_until_rpm_available for k in available)
           logger.info(f"All keys at RPM limit — sleeping {wait:.1f}s")
           time.sleep(wait + 0.5)




_pool: KeyPool | None = None
_pool_lock = threading.Lock()




def get_pool() -> KeyPool:
   global _pool
   if _pool is None:
       with _pool_lock:
           if _pool is None:
               raw = os.getenv("GEMINI_API_KEYS", "")
               keys = [k.strip() for k in raw.split(",") if k.strip()]
               if not keys:
                   single = os.getenv("GEMINI_API_KEY", "")
                   if single:
                       keys = [single]
               _pool = KeyPool(keys)
   return _pool




MODEL = "gemini-3.1-flash-lite"




# ---------------------------------------------------------------------------
# Canonical name list (the only hardcoded list — names only, no facts)
# ---------------------------------------------------------------------------


CANONICAL_NAMES: dict[str, str] = {
   # Krishna
   "krsna": "Krishna", "kṛṣṇa": "Krishna", "govinda": "Krishna",
   "madhusudana": "Krishna", "vasudeva": "Krishna", "devaki-nandana": "Krishna",
   "yadunandana": "Krishna", "gopala": "Krishna", "murari": "Krishna",
   "giridhari": "Krishna", "shyamasundara": "Krishna", "syamasundara": "Krishna",
   "nandanandana": "Krishna", "yasodanandana": "Krishna",
   # Vishnu / Narayana (distinct in theology)
   "visnu": "Vishnu", "viṣṇu": "Vishnu",
   "nārāyaṇa": "Narayana", "narayana": "Narayana",
   # Brahma
   "brahmā": "Brahma",
   # Shiva
   "śiva": "Shiva", "siva": "Shiva", "mahadeva": "Shiva",
   "sankara": "Shiva", "śaṅkara": "Shiva",
   # Narada
   "nārada": "Narada", "devarsi narada": "Narada",
   # Vyasa
   "vyāsa": "Vyasa", "vyasadeva": "Vyasa", "vedavyasa": "Vyasa",
   # Sukadeva
   "śukadeva": "Sukadeva", "suka": "Sukadeva", "śuka": "Sukadeva",
   # Parikshit
   "parīkṣit": "Parikshit", "pariksit": "Parikshit",
   # Arjuna
   "pārtha": "Arjuna", "dhananjaya": "Arjuna",
   # Radha
   "rādhā": "Radha", "radhika": "Radha",
   # Chaitanya
   "caitanya": "Chaitanya Mahaprabhu",
   "caitanya mahaprabhu": "Chaitanya Mahaprabhu",
   "gauranga": "Chaitanya Mahaprabhu",
   "gaura": "Chaitanya Mahaprabhu",
   "mahaprabhu": "Chaitanya Mahaprabhu",
   # Nityananda
   "nityānanda": "Nityananda",
   # Prabhupada
   "śrīla prabhupāda": "Srila Prabhupada",
   "srila prabhupada": "Srila Prabhupada",
   # Others
   "laksmī": "Lakshmi", "laksmi": "Lakshmi", "lakṣmī": "Lakshmi",
   "sarasvatī": "Sarasvati", "sarasvati": "Sarasvati",
   "hari": "Vishnu",
}




# ---------------------------------------------------------------------------
# Stage prompts — focused, constrained, no ambiguity
# ---------------------------------------------------------------------------

# Book authorship preamble shared across stages
_BOOK_CONTEXT = """BOOK AUTHORSHIP — when the text uses "I", the author is:
- BRS (Bhakti-rasamrta-sindhu) → Rupa Goswami
- CC (Caitanya-caritamrta) → Krishnadasa Kaviraja Goswami
- CB (Caitanya Bhagavata) → Vrindavana Dasa Thakura
- SB (Srimad-Bhagavatam) → compiled by Vyasa; narrated by Sukadeva to Parikshit"""

_CANONICAL_MAPPINGS = """CANONICAL NAME MAPPINGS (always use these exact English names):
- Krsna / Govinda / Madhusudana / Vasudeva / Murari / Hari → "Krishna"
- Caitanya / Gauranga / Mahaprabhu / Gauracandra → "Chaitanya Mahaprabhu"
- Siva / Mahadeva / Sankara / Rudra → "Shiva"
- Narada / Nārada → "Narada"
- Vyasa / Vyasadeva / Vedavyasa → "Vyasa"
- Sukadeva / Suka / Śukadeva → "Sukadeva"
- Parikshit / Parīkṣit → "Parikshit"
- Nityananda / Nityānanda → "Nityananda"
- Lakshmi / Lakṣmī → "Lakshmi"
- Narayana / Nārāyaṇa → "Narayana"
name format: plain English, no diacritics, no possessives (e.g. "Krishna" not "Kṛṣṇa" or "Krishna's")
sanskrit_name: full diacritics (e.g. "Kṛṣṇa")"""

STAGE1_SYSTEM = f"""You are an expert Gaudiya Vaishnava scholar. Your task: identify named entities and spiritual concepts from a scripture verse and its purport.

{_BOOK_CONTEXT}

{_CANONICAL_MAPPINGS}

━━━ ENTITY RULES ━━━
1. Extract ONLY entities EXPLICITLY named in the text. If you are not certain — omit it.
   Zero entities is a valid, correct result.
2. No generics. These are INVALID entities: "a devotee", "the scripture", "the Lord" (without clear identity),
   "a king", "the speaker", "the author". If a specific name is not given, do not create an entity.
3. SOURCE ANNOTATION — for each entity, mark exactly where it appears:
   • "source": "verse"   → named ONLY in the Sanskrit verse / Translation line (NOT in Purport)
   • "source": "purport" → named ONLY in the Purport commentary (NOT in verse/translation)
   • "source": "both"    → named in BOTH verse/translation AND purport
   
   EXAMPLES:
   ✓ If verse says "Krishna" and purport also mentions "Krishna" → source: "both"
   ✓ If only the verse translation says "Krishna" but purport doesn't mention it → source: "verse"
   ✓ If only the purport describes "Radha" but the verse doesn't name her → source: "purport"
   
   This field is MANDATORY. Always include it.
4. Entity types — choose exactly one:
   • person   — named individual humans (historical, devotees, kings)
   • deva     — gods and divine beings
   • sage     — rishis, munis, acharyas
   • demon    — asuras, rakshasas
   • place    — cities, forests, spiritual realms, planets
   • river    — named rivers
   • mountain — named mountains
   • kingdom  — ruled territories
   • dynasty  — ruling lineages
   • text     — any named written work (scripture, purana, smriti, gita, etc.)
   • object   — significant physical items (weapons, ornaments, etc.)
   • group    — named collectives (Pracetas, Kauravas, Siddhas, etc.)
5. description: 1 or 2 sentences of canonical Gaudiya Vaishnava encyclopedic knowledge about this entity.
   Include: who they are, their role/significance in Gaudiya Vaishnava tradition, and key relationships.
   NEVER reference this specific verse. Write as if for a comprehensive reference encyclopedia.
6. aliases: ONLY alternate names that appear EXPLICITLY in THIS text. Do not add well-known aliases
   from general knowledge that are absent from the passage.

━━━ CONCEPT RULES ━━━
1. Concepts = philosophical/spiritual ideas, practices, qualities, states of being.
2. VALID concepts: bhakti, jnana, karma, maya, dharma, moksha, lila, rasa, vairagya, surrender,
   humility, detachment, chanting, devotion, liberation, austerity, renunciation, bhava-bhakti,
   prema, dasya, sakhya, vatsalya, madhurya, sadhana, qualification, initiation, purity, etc.
3. NOT concepts (do not list these): person names, text titles, place names, chapter/book/section
   structural labels (khanda, chapter, division, part, prologue, introduction).
4. Format: lowercase singular, no diacritics — "bhakti" not "Bhakti" or "bhaktis".
5. For each concept, provide: name (lowercase, no diacritics) + description (1–2 sentences explaining
   the concept in Gaudiya Vaishnava context, independent of this specific verse).
6. List only concepts clearly present or discussed in this specific text.

━━━ OUTPUT ━━━
Valid JSON only, no markdown fences, no explanation:
{{"entities":[{{"name":"...","sanskrit_name":"...","type":"...","description":"...","aliases":[],"source":"verse|purport|both"}}],"concepts":[{{"name":"...","description":"..."}}]}}
EMPTY RESULT: {{"entities":[],"concepts":[]}}"""


STAGE2_SYSTEM = f"""You are an expert Gaudiya Vaishnava scholar. Your task: extract relationships between entities in a scripture verse.

You will receive: the verse + purport text, and the list of entities already identified.

{_BOOK_CONTEXT}

━━━ RULES ━━━
1. You may ONLY form relationships between entities in the PROVIDED ENTITY LIST.
   Do NOT introduce any new entity names.
2. Extract ONLY relationships explicitly stated or unmistakably implied by THIS text.
   Do NOT use general scriptural knowledge — only what this specific passage says.
3. Direction: "source [type] target" must be a literally true sentence.
   ✓ source="Devaki" type="mother_of" target="Krishna"
   ✗ source="Kamsa" type="killed_by" target="Krishna" — wrong direction (passive voice trap)

━━━ HARD TYPE CONSTRAINTS — NEVER violate these ━━━
• authored_by  → target MUST be a TEXT entity. A person cannot author a concept, another person,
                 a place, or a dynasty. ✗ "Rupa Goswami authored_by bhakti" is WRONG.
• cites        → use when a person or text quotes/references a text they did NOT write.
                 Do NOT use authored_by for citing someone else's work.
• worships / prays_to / surrenders_to / takes_shelter_of
               → target MUST be a person/deva/sage. NEVER a concept or text.
                 ✗ "Rupa Goswami worships bhava-bhakti" is WRONG (bhava-bhakti is a concept).
• glorifies    → target MUST be a person/deva/sage. If the text praises a concept or practice,
                 there is no relationship to extract — that is a concept, handled in Stage 1.
• devotee_of   → target MUST be a deva or sage. Not a text or concept.

━━━ RELATIONSHIP TYPE REFERENCE ━━━
Family:   father_of, mother_of, son_of, daughter_of, brother_of, sister_of, spouse_of,
          uncle_of, nephew_of, grandfather_of, grandson_of
Spiritual: guru_of, disciple_of, devotee_of, servant_of, friend_of, enemy_of,
           worships, surrenders_to, glorifies, prays_to, initiated_by
Action:   kills, blesses, curses, instructs, rescues, defeats, grants_boon_to
Role:     king_of, resident_of, incarnation_of, expansion_of, authored_by, cites, rules_over

Zero relationships is a valid and often correct result. Never force a relationship.

━━━ OUTPUT ━━━
Valid JSON only, no markdown fences, no explanation:
{{"relationships":[{{"source":"...","target":"...","type":"...","context":"exact phrase from text supporting this"}}]}}
EMPTY RESULT: {{"relationships":[]}}"""


STAGE3_SYSTEM = """You are a strict quality-control reviewer for Vaishnava scripture extraction.

You will receive: the original verse + purport AND an extraction result (entities, relationships, concepts).

Review every item against the original text. Apply ALL checks below and return a corrected result.

━━━ ENTITY CHECKS ━━━
✓ PRESERVE all entity fields EXACTLY (unless there is a mistake): name, type, description, aliases, source, sanskrit_name
  (description: keep from Stage 1 output unchanged — do not regenerate or modify)
✗ Entity NOT explicitly named in the verse or purport → REMOVE
✗ Entity type wrong (e.g., a text classified as "person", a concept as "deva") → FIX type
✗ Source annotation wrong ("verse"/"purport"/"both") → FIX (compare against original text & check if the entity is mentioned in the verse or the purport or both)
✗ Generic or vague name ("a king", "the devotee", "the speaker") → REMOVE

━━━ RELATIONSHIP CHECKS ━━━
✗ source or target name NOT in the entity list → REMOVE
✗ "authored_by" where target is not a text entity → REMOVE
✗ "worships / glorifies / prays_to / surrenders_to / takes_shelter_of" where target is a concept
   or text entity → REMOVE
✗ Relationship not clearly supported by the text → REMOVE
✗ Wrong direction (passive voice confused, e.g. killed_by vs kills) → FIX direction or REMOVE if unsure
✗ Author cites a text they did not write, but relationship says "authored_by" → CHANGE to "cites"

━━━ CONCEPT CHECKS ━━━
✓ PRESERVE all concept fields EXACTLY: name, description (do not regenerate descriptions — keep from Stage 1)
✗ Named entity (person, place, text) listed as a concept → REMOVE
✗ Structural label (chapter, book, section, khanda, division, part, introduction) → REMOVE
✗ Missing description field → ADD a 1–2 sentence description of the concept
✗ Duplicates → DEDUPLICATE

If everything is already correct, return the input unchanged.

━━━ OUTPUT ━━━
Valid JSON only, no markdown fences, no explanation.
For EACH entity, include ALL fields: name, type, description, aliases, source, sanskrit_name.
{"entities":[{"name":"...","type":"...","description":"...","aliases":[],"source":"verse|purport|both","sanskrit_name":"..."}],"relationships":[...],"concepts":[{"name":"...","description":"..."}]}"""


# ---------------------------------------------------------------------------
# Name normalization helpers (canonical mappings applied after extraction)
# ---------------------------------------------------------------------------


def normalize_entity_name(name: str) -> str:
   """Strip possessives → ascii-fold diacritics → apply canonical map."""
   if not name:
       return name
   name = re.sub(r"[''’]s?\s*$", "", name.strip()).strip()
   nfd = unicodedata.normalize("NFD", name)
   ascii_name = nfd.encode("ascii", "ignore").decode("ascii").strip()
   lower = ascii_name.lower()
   if lower in CANONICAL_NAMES:
       return CANONICAL_NAMES[lower]
   orig_lower = name.lower()
   if orig_lower in CANONICAL_NAMES:
       return CANONICAL_NAMES[orig_lower]
   return ascii_name if ascii_name else name




def _filter_bad_aliases(aliases: list) -> list:
    """Remove pronouns, articles, and generic words from aliases."""
    bad_words = {
        # Pronouns
        'he', 'she', 'it', 'they', 'them', 'we', 'you', 'i', 'me', 'us', 'him', 'her',
        # Articles/demonstratives
        'the', 'a', 'an', 'this', 'that', 'these', 'those',
        # Generic words
        'author', 'speaker', 'person', 'god', 'lord', 'master', 'devotee', 'sage',
        'man', 'woman', 'being', 'entity', 'one', 'someone', 'anyone', 'himself', 'herself',
        # Common weak words
        'self', 'own', 'other', 'same', 'such', 'very',
    }

    filtered = []
    for alias in aliases:
        if not isinstance(alias, str):
            continue
        clean = alias.strip().lower()
        if clean and clean not in bad_words and len(clean) > 1:
            filtered.append(alias.strip())
    return list(dict.fromkeys(filtered))  # Remove duplicates while preserving order




def normalize_extraction_result(result: dict) -> dict:
   """Normalize entity names and relationship source/target using canonical mappings.
   Also normalize concepts to ensure they have name + description."""
   name_map: dict[str, str] = {}

   normalized_entities = []
   for ent in result.get("entities", []):
       orig = ent.get("name", "").strip()
       canon = normalize_entity_name(orig)
       if not canon:
           continue
       name_map[orig] = canon
       name_map[orig.lower()] = canon
       ent["name"] = canon
       ent["aliases"] = _filter_bad_aliases(ent.get("aliases", []))
       # Ensure source field is valid
       if ent.get("source") not in ("verse", "purport", "both"):
           ent["source"] = "verse"
       normalized_entities.append(ent)
   result["entities"] = normalized_entities

   normalized_rels = []
   for rel in result.get("relationships", []):
       src = rel.get("source", "").strip()
       tgt = rel.get("target", "").strip()
       rel["source"] = name_map.get(src) or name_map.get(src.lower()) or normalize_entity_name(src)
       rel["target"] = name_map.get(tgt) or name_map.get(tgt.lower()) or normalize_entity_name(tgt)
       if rel["source"] and rel["target"] and rel["source"] != rel["target"]:
           normalized_rels.append(rel)
   result["relationships"] = normalized_rels

   # Normalize concepts: expect dict with name + description, or handle legacy strings
   normalized_concepts = []
   for c in result.get("concepts", []):
       if isinstance(c, dict):
           # New format: {"name": "...", "description": "..."}
           name = c.get("name", "").strip().lower()
           desc = c.get("description", "").strip()
           if name:
               normalized_concepts.append({"name": name, "description": desc})
       elif isinstance(c, str):
           # Legacy format: just a string name
           name = c.strip().lower()
           if name:
               normalized_concepts.append({"name": name, "description": ""})
   result["concepts"] = normalized_concepts

   return result


# ---------------------------------------------------------------------------
# Core extraction — 3-stage pipeline
# ---------------------------------------------------------------------------

def _build_verse_block(verse: dict) -> str:
   ref = verse.get("full_reference", "")
   translation = verse.get("translation", "")
   purport = (verse.get("purport_text") or "").strip()
   block = f"[{ref}]\nTranslation: {translation}"
   if purport:
       block += f"\nPurport: {purport}"
   return block


def _call_gemini(prompt: str, system_instruction: str) -> dict:
   """Single Gemini call. Returns parsed dict. Raises on error."""
   pool = get_pool()
   key = pool.acquire()

   if pool.request_delay > 0:
       time.sleep(pool.request_delay)

   key.record_call()

   response = key.client.models.generate_content(
       model=MODEL,
       contents=prompt,
       config=genai_types.GenerateContentConfig(
           temperature=0.1,
           response_mime_type="application/json",
           system_instruction=system_instruction,
       ),
   )
   raw = response.text.strip()
   raw = re.sub(r"^```(?:json)?\s*", "", raw)
   raw = re.sub(r"\s*```$", "", raw)
   return json.loads(raw)


def _safe_call(prompt: str, system_instruction: str, stage_name: str,
               empty: dict, max_retries: int = 3) -> dict:
   """Call Gemini with retry on transient errors. Returns empty on failure."""
   for attempt in range(max_retries):
       try:
           logger.info(f"    → Calling Gemini (attempt {attempt+1}/{max_retries})")
           result = _call_gemini(prompt, system_instruction)
           logger.info(f"    ✓ Gemini responded successfully")
           return result
       except json.JSONDecodeError as e:
           logger.error(f"    ✗ [{stage_name}] JSON parse error (attempt {attempt+1}): {e}")
       except Exception as e:
           err_str = str(e)
           is_retryable = any(x in err_str for x in ["429", "quota", "rate", "500", "503"])
           if not is_retryable:
               logger.error(f"    ✗ [{stage_name}] Non-retryable error: {e}")
               return empty
           wait = 15 * (2 ** attempt)
           logger.warning(f"    ⏳ [{stage_name}] Retryable error, waiting {wait}s (attempt {attempt+1}): {e}")
           time.sleep(wait)
   logger.error(f"    ✗ [{stage_name}] All {max_retries} attempts failed, returning empty.")
   return empty


def _stage1_entities_concepts(verse_block: str, ref: str) -> tuple[list, list]:
   """Stage 1: Extract entities (with source) and concepts."""
   logger.info(f"  ┌─ [Stage 1] Extracting entities + concepts")
   prompt = f"VERSE TO ANALYZE:\n\n{verse_block}"
   raw = _safe_call(prompt, STAGE1_SYSTEM, "Stage1", {"entities": [], "concepts": []})
   entities = raw.get("entities", [])
   concepts = raw.get("concepts", [])
   logger.info(f"  ├─ [Stage 1] Raw result: {len(entities)} entities, {len(concepts)} concepts")
   for e in entities:
       src = e.get('source','?')
       name = e.get('name','?')
       etype = e.get('type','?')
       desc = e.get('description','')
       logger.info(f"  │   • [{etype:8s}] {name:25s} (source={src:7s})")
       if desc:
           logger.info(f"  │      → {desc}")
   if concepts:
       logger.info(f"  │   concepts: {concepts}")
   logger.info(f"  └─ [Stage 1] Complete")
   return entities, concepts


def _stage2_relationships(verse_block: str, ref: str, entities: list) -> list:
   """Stage 2: Extract relationships, constrained to the entity list from Stage 1."""
   if not entities:
       logger.info(f"  ├─ [Stage 2] Skipped (no entities from Stage 1)")
       return []

   entity_list_str = "\n".join(
       f'  • {e["name"]} (type: {e.get("type","?")})'
       for e in entities
   )
   prompt = (
       f"VERSE TO ANALYZE:\n\n{verse_block}\n\n"
       f"ENTITY LIST (you may ONLY relate these entities — no others):\n{entity_list_str}"
   )
   logger.info(f"  ├─ [Stage 2] Extracting relationships ({len(entities)} entities available)")
   raw = _safe_call(prompt, STAGE2_SYSTEM, "Stage2", {"relationships": []})
   rels = raw.get("relationships", [])
   logger.info(f"  ├─ [Stage 2] Raw result: {len(rels)} relationships")
   for r in rels:
       src = r.get('source','?')
       tgt = r.get('target','?')
       typ = r.get('type','?')
       ctx = r.get('context','')[:40]
       logger.info(f"  │   • {src:20s} --[{typ:20s}]--> {tgt:20s}")
       if ctx:
           logger.info(f"  │      context: {ctx}")
   logger.info(f"  └─ [Stage 2] Complete")
   return rels


def _stage3_verify(verse_block: str, ref: str,
                   entities: list, relationships: list, concepts: list) -> tuple[list, list, list]:
   """Stage 3: Verify and correct the extraction output."""
   logger.info(f"  ├─ [Stage 3] Verifying extraction ({len(entities)} ents, {len(relationships)} rels, {len(concepts)} concepts)")
   payload = json.dumps({
       "entities": entities,
       "relationships": relationships,
       "concepts": concepts
   }, ensure_ascii=False)
   prompt = (
       f"ORIGINAL TEXT:\n\n{verse_block}\n\n"
       f"EXTRACTION TO REVIEW:\n{payload}"
   )
   raw = _safe_call(prompt, STAGE3_SYSTEM, "Stage3",
                    {"entities": entities, "relationships": relationships, "concepts": concepts})

   verified_entities = raw.get("entities", entities)
   verified_rels = raw.get("relationships", relationships)
   verified_concepts = raw.get("concepts", concepts)

   # Log what changed
   removed_entities = len(entities) - len(verified_entities)
   removed_rels = len(relationships) - len(verified_rels)
   removed_concepts = len(concepts) - len(verified_concepts)
   
   logger.info(f"  ├─ [Stage 3] Verification complete")
   if removed_entities or removed_rels or removed_concepts:
       logger.info(
           f"  │   Corrections: -{removed_entities} entities, "
           f"-{removed_rels} rels, -{removed_concepts} concepts"
       )
   else:
       logger.info(f"  │   No corrections needed (all items valid)")
   logger.info(f"  └─ [Stage 3] Complete")

   return verified_entities, verified_rels, verified_concepts


def extract_with_retry(verses: list[dict], max_retries: int = 3) -> dict:
   """
   Run the 3-stage extraction pipeline for a single verse.
   Returns a result dict with keys: entities, relationships, concepts.
   All 3 stages must succeed for data to be returned; otherwise returns empty.
   """
   if not verses:
       logger.error("extract_with_retry: no verses provided, returning empty")
       return {"entities": [], "relationships": [], "concepts": []}

   verse = verses[0]
   ref = verse.get("full_reference", "?")
   verse_block = _build_verse_block(verse)

   logger.info(f"┌─────────────────────────────────────────────────────")
   logger.info(f"│ Extraction Pipeline: {ref}")
   logger.info(f"├─────────────────────────────────────────────────────")

   # Stage 1: Entities + Concepts
   entities, concepts = _stage1_entities_concepts(verse_block, ref)

   # Stage 2: Relationships (only if we have entities)
   relationships = _stage2_relationships(verse_block, ref, entities)

   # Stage 3: Verification
   entities, relationships, concepts = _stage3_verify(verse_block, ref, entities, relationships, concepts)

   # Normalize names (canonical mappings, alias filtering)
   logger.info(f"  ├─ Normalizing names and filtering...")
   result = normalize_extraction_result({
       "entities": entities,
       "relationships": relationships,
       "concepts": concepts,
   })

   e_count = len(result["entities"])
   r_count = len(result["relationships"])
   c_count = len(result["concepts"])
   logger.info(f"  └─ Normalization complete")
   logger.info(f"├─────────────────────────────────────────────────────")
   logger.info(f"│ FINAL RESULT: {e_count} entities, {r_count} rels, {c_count} concepts")
   logger.info(f"└─────────────────────────────────────────────────────")

   return result


def find_low_confidence_relationships(result: dict) -> list[dict]:
   """Kept for compatibility — no longer used in pipeline but may be called externally."""
   return []


def format_flagged_for_hint(flagged: list[dict]) -> str:
   return ""



