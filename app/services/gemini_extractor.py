"""
Gemini-powered entity & relationship extractor for Bhagavatam texts.


Key pool: set GEMINI_API_KEYS=key1,key2,key3 in .env
Per key limits: 15 RPM, 500 RPD
The pool rotates so the daily budget is never exhausted.


Relationship quality:
- Each relationship carries a "confidence": high | medium | low field.
- The model self-checks every relationship before returning.
- If any low-confidence relationships remain after extraction, the verse is
 retried (up to MAX_VERIFY_RETRIES times) with a hint listing the suspicious
 relationships so the model can re-examine them.
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
MAX_VERIFY_RETRIES = 2   # extra attempts when low-confidence rels are found
HOURS_TO_RUN = 24  # spread requests over this many hours (24 = full day, 8 = business hours)
# REQUEST_DELAY_SECONDS is calculated dynamically based on number of keys




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
# Prompt — compact system instruction + worked example
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = """You are an expert Vaishnava scholar (SB, CC, CB, BRS). Given ONE verse with translation and purport, extract entities, relationships, and concepts.

## BOOK CONTEXT — AUTHOR IDENTIFICATION
The verse reference prefix tells you who the author/speaker is when the text uses "I":
- BRS (Bhakti-rasamrta-sindhu) → author is **Rupa Goswami**
- CC (Caitanya-caritamrta) → author is **Krishnadasa Kaviraja Goswami**
- CB (Caitanya Bhagavata) → author is **Vrindavana Dasa Thakura**
- SB (Srimad-Bhagavatam) → compiled by Vyasa; narrated by Sukadeva to Parikshit

When a verse uses first-person ("I offer my respects", "I have undertaken this work", "I am ignorant"), extract the author as an entity and add a relationship like `authored_by` or `worships` as appropriate.

## NAMES
- "name": plain English, no diacritics, no possessives — "Krishna" not "Kṛṣṇa" or "Krishna's"
- "sanskrit_name": full diacritics
- Same canonical name everywhere (entities, relationships, verse_summaries)
- Canonical mappings:
  Krsna/Govinda/Madhusudana/Vasudeva/Murari/Hari → "Krishna"
  Visnu/Narayana/Hari(Narayana context) → "Vishnu"
  Brahma/Brahmā → "Brahma"
  Siva/Mahadeva/Sankara/Rudra → "Shiva"
  Nārada → "Narada" | Vyāsa/Vyasadeva → "Vyasa" | Śukadeva/Suka → "Sukadeva"
  Parīkṣit → "Parikshit" | Caitanya/Gauranga/Gauracandra → "Chaitanya Mahaprabhu"

## ENTITY TYPES
Extract only entities that are clearly and meaningfully present. Fewer accurate entities are better than many uncertain ones — if you are not confident an entity belongs, omit it.

| type | notes |
|------|-------|
| person | named humans only — NOT devotee categories or archetypes |
| deva | gods/divine beings |
| demon | asuras, rakshasas |
| sage | rishis, munis |
| animal | named animals only |
| place | cities, forests, realms — Vrindavan, Vaikuntha, spiritual world ARE places, NOT concepts |
| river | any named river |
| mountain | any named mountain |
| kingdom | ruled territories |
| dynasty | ruling lineages |
| concept | philosophical ideas, virtues, vices, spiritual practices — NOT book divisions/chapters/sections |
| object | significant physical items |
| text | scriptural works |

**description**: Gaudiya Vaishava specific encyclopedic knowledge about this entity — never specific to this verse. Keep to 1–2 sentences.
**aliases**: ONLY alternate names that explicitly appear in this verse or purport text. Do not add well-known aliases that are absent from the passage.

## RELATIONSHIPS
Extract ONLY what is explicitly stated or clearly implied in THIS text. Do NOT add general scriptural knowledge absent from the passage.
If no clear relationship exists between two entities, DO NOT invent one — it is better to have zero relationships than a forced or wrong one.

"source [type] target" must be a true statement — direction matters.
✓ source="Devaki" type="mother_of" target="Krishna"
✗ source="Kamsa" type="killed_by" target="Krishna" (passive voice — wrong)

Preferred types (you may invent a precise type if none fits):
- Family: father_of, mother_of, son_of, daughter_of, brother_of, sister_of, spouse_of, uncle_of, nephew_of, cousin_of, grandfather_of, grandson_of, stepfather_of, stepmother_of, father_in_law_of, adopted_son_of
- Spiritual: guru_of, disciple_of, devotee_of, servant_of, friend_of, enemy_of, worships, surrenders_to, takes_shelter_of, glorifies, prays_to, initiated_by
- Action: kills, blesses, curses, instructs, rescues, protects, liberates, sends, receives, steals, imprisons, defeats, grants_boon_to
- Role/identity: king_of, minister_of, commander_of, resident_of, incarnation_of, expansion_of, avatar_of, manifests_as, rules_over, born_in, located_in, authored_by, associated_with

Confidence: high = explicit in text; medium = clearly implied; low = omit entirely

## ENTITY QUALITY
Do NOT extract vague catch-all entities. These are the most common offenders:
- "scripture" / "the scriptures" → extract the SPECIFIC named text (Skanda Purana, Bhagavad Gita) OR skip it; "scripture" as a generic node produces meaningless relationships
- "devotee", "the practitioner", "a person", "one who" → these describe a category, not a named individual; extract the concept instead (e.g. "uttamādhikārī" as a concept)
- "the Lord", "the Supreme" without context → resolve to the specific deity only if the passage makes it unambiguous; if it could be Krishna or Vishnu or another, skip the entity rather than guess

A generic entity as a relationship source/target is a red flag — if you find yourself writing `source="scripture"`, stop and reconsider.

## CONCEPTS
Valid: bhakti, jnana, karma, maya, dharma, moksha, lila, rasa, vairagya, austerity, humility, surrender, attachment, detachment, pride, compassion, dasya, sakhya, vatsalya, madhurya, chanting, lust, anger, greed, vaidhi-bhakti, raganuga-bhakti, sadhana-bhakti, bhava-bhakti, prema-bhakti, uttama-bhakti, etc.
Devotee qualification levels are CONCEPTS, not persons: uttamadhikari, madhyamadhikari, kanisthadhikari — these are categories, not named individuals. Use plain English lowercase (no diacritics) for concept names.
Invalid: Adi Khanda, Madhya Khanda, chapter, section, part, division, book, khanda, introduction, prologue — these are structural labels, not ideas.
Format: lowercase singular — "bhakti" not "Bhakti" or "bhaktis"; never include "the"

## EXAMPLE

Input:
[SB 10.3.9]
Translation: O Lord, You are the source of the entire creation...
Purport: Devaki recognizes Krishna as the Supreme Person and prays with great humility...

Output:
{"entities":[{"name":"Krishna","sanskrit_name":"Kṛṣṇa","type":"deva","description":"The Supreme Personality of Godhead, source of all avatars and the original person.","aliases":[]},{"name":"Devaki","sanskrit_name":"Devakī","type":"person","description":"Mother of Krishna, wife of Vasudeva, imprisoned by her brother Kamsa.","aliases":[]},{"name":"humility","sanskrit_name":"vinaya","type":"concept","description":"The quality of being free from pride; a foundational virtue in Vaishnava practice.","aliases":[]}],"relationships":[{"source":"Devaki","target":"Krishna","type":"mother_of","context":"Devaki addresses Krishna at his birth","confidence":"high"},{"source":"Devaki","target":"Krishna","type":"worships","context":"Devaki prays to Krishna with humility","confidence":"high"}],"verse_summaries":[{"reference":"SB 10.3.9","entities_mentioned":[{"name":"Krishna","source":"verse"},{"name":"Devaki","source":"purport"}],"concepts":["humility"]}]}

## OUTPUT — valid JSON only, no markdown fences
{"entities":[...],"relationships":[...],"verse_summaries":[{"reference":"...","entities_mentioned":[{"name":"...","source":"verse|purport"}],"concepts":["..."]}]}

EMPTY RESULT: {"entities":[],"relationships":[],"verse_summaries":[]}
"""


RETRY_HINT_TEMPLATE = """
IMPORTANT — Your previous extraction had these uncertain or potentially incorrect relationships:
{flagged}


Please re-examine the verse and purport carefully for each of these.
Ask yourself: "Does [source] [type] [target] state a TRUE fact from Vaishnava scripture, in the correct direction?"
- If the fact is correct but direction is wrong, swap source and target.
- If you are still uncertain, remove the relationship entirely rather than guessing.
- Only include relationships with confidence "high" or "medium".
"""




# ---------------------------------------------------------------------------
# Name normalization helpers
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
   """Apply name normalization to all entity names and relationship source/target."""
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
       # Filter bad aliases
       ent["aliases"] = _filter_bad_aliases(ent.get("aliases", []))
       normalized_entities.append(ent)
   result["entities"] = normalized_entities


   entity_names = {e["name"] for e in normalized_entities}


   normalized_rels = []
   for rel in result.get("relationships", []):
       src = rel.get("source", "").strip()
       tgt = rel.get("target", "").strip()
       rel["source"] = name_map.get(src) or name_map.get(src.lower()) or normalize_entity_name(src)
       rel["target"] = name_map.get(tgt) or name_map.get(tgt.lower()) or normalize_entity_name(tgt)
       # Drop self-relationships or ones with empty/unknown names
       if (rel["source"] and rel["target"]
               and rel["source"] != rel["target"]):
           normalized_rels.append(rel)
   result["relationships"] = normalized_rels


   for vs in result.get("verse_summaries", []):
       fixed = []
       for mention in vs.get("entities_mentioned", []):
           if isinstance(mention, dict):
               n = mention.get("name", "").strip()
               mention["name"] = name_map.get(n) or name_map.get(n.lower()) or normalize_entity_name(n)
               if mention["name"]:
                   fixed.append(mention)
           else:
               canon = name_map.get(mention) or name_map.get(mention.lower()) or normalize_entity_name(mention)
               if canon:
                   fixed.append({"name": canon, "source": "verse"})
       vs["entities_mentioned"] = fixed


   return result




# ---------------------------------------------------------------------------
# Quality checks
# ---------------------------------------------------------------------------


def find_low_confidence_relationships(result: dict) -> list[dict]:
   """Return relationships marked low-confidence or with structural issues."""
   flagged = []
   entity_names = {e["name"] for e in result.get("entities", [])}
   for rel in result.get("relationships", []):
       reasons = []
       if rel.get("confidence", "high") == "low":
           reasons.append("confidence=low")
       if rel["source"] not in entity_names:
           reasons.append(f"source '{rel['source']}' not in entities list")
       if rel["target"] not in entity_names:
           reasons.append(f"target '{rel['target']}' not in entities list")
       if reasons:
           flagged.append({**rel, "_reasons": reasons})
   return flagged




def format_flagged_for_hint(flagged: list[dict]) -> str:
   lines = []
   for r in flagged:
       reasons = ", ".join(r.get("_reasons", []))
       lines.append(
           f'  - source="{r["source"]}" type="{r["type"]}" target="{r["target"]}" '
           f'[{reasons}]'
       )
   return "\n".join(lines)




# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------


def _build_verse_block(verse: dict) -> str:
   ref = verse.get("full_reference", "")
   translation = verse.get("translation", "")
   purport = (verse.get("purport_text") or "").strip()
   block = f"[{ref}]\nTranslation: {translation}"
   if purport:
       block += f"\nPurport: {purport}"
   return block




def _call_gemini(prompt: str) -> dict:
   """Single Gemini call with key pool management. Returns parsed dict."""
   pool = get_pool()
   key = pool.acquire()


   # Apply request delay for daily rate pacing (calculated based on number of keys)
   if pool.request_delay > 0:
       time.sleep(pool.request_delay)


   key.record_call()


   response = key.client.models.generate_content(
       model=MODEL,
       contents=prompt,
       config=genai_types.GenerateContentConfig(
           temperature=0.1,
           response_mime_type="application/json",
           system_instruction=SYSTEM_PROMPT,
       ),
   )
   raw = response.text.strip()
   raw = re.sub(r"^```(?:json)?\s*", "", raw)
   raw = re.sub(r"\s*```$", "", raw)
   return json.loads(raw)




def extract_from_verses(verses: list[dict], hint: str = "") -> dict:
   """
   Call Gemini to extract entities/relationships from verses (send 1 at a time).
   If hint is provided (retry context), it is appended to the prompt.
   """
   verse_blocks = "\n\n---\n\n".join(_build_verse_block(v) for v in verses)
   prompt = f"VERSE TO ANALYZE:\n\n{verse_blocks}"
   if hint:
       prompt += f"\n\n{hint}"


   result = _call_gemini(prompt)
   return normalize_extraction_result(result)




def extract_with_retry(verses: list[dict], max_retries: int = 5) -> dict:
   """
   Full retry pipeline:
   1. Extract from verses.
   2. If low-confidence or structural issues found, retry with a hint
      (up to MAX_VERIFY_RETRIES extra attempts).
   3. On API errors, use exponential backoff (up to max_retries total attempts).
   """
   hint = ""
   result = {"entities": [], "relationships": [], "verse_summaries": []}


   for api_attempt in range(max_retries):
       try:
           result = extract_from_verses(verses, hint=hint)
           break
       except json.JSONDecodeError as e:
           logger.error(f"JSON parse error attempt {api_attempt+1}: {e}")
           if api_attempt == max_retries - 1:
               return {"entities": [], "relationships": [], "verse_summaries": []}
           time.sleep(5)
           continue
       except Exception as e:
           err_str = str(e).lower()
           is_retryable = any(x in err_str for x in ["429", "quota", "rate", "500", "503", "internal"])
           if not is_retryable or api_attempt == max_retries - 1:
               logger.error(f"Gemini error (non-retryable or max retries): {e}")
               return {"entities": [], "relationships": [], "verse_summaries": []}
           wait = 15 * (2 ** api_attempt)
           logger.warning(f"Retryable error, waiting {wait}s: {e}")
           time.sleep(wait)
           continue


   # Quality verification loop — retry if low-confidence relationships found
   for verify_attempt in range(MAX_VERIFY_RETRIES):
       flagged = find_low_confidence_relationships(result)
       if not flagged:
           break
       logger.warning(
           f"  Found {len(flagged)} uncertain relationship(s) — retry {verify_attempt+1}/{MAX_VERIFY_RETRIES}"
       )
       for f in flagged:
           logger.warning(f"    {f['source']} --{f['type']}--> {f['target']} ({', '.join(f.get('_reasons', []))})")


       hint = RETRY_HINT_TEMPLATE.format(flagged=format_flagged_for_hint(flagged))
       try:
           new_result = extract_from_verses(verses, hint=hint)
           # Only accept the retry if it has at least as many entities
           if len(new_result.get("entities", [])) >= len(result.get("entities", [])) // 2:
               result = new_result
           else:
               logger.warning("  Retry returned fewer entities — keeping original")
               break
       except Exception as e:
           logger.error(f"  Verification retry failed: {e}")
           break


   # Final pass: drop any remaining low-confidence relationships
   result["relationships"] = [
       r for r in result.get("relationships", [])
       if r.get("confidence", "high") != "low"
   ]


   return result



