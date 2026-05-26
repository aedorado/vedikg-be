"""
Gemini-powered entity & relationship extractor for Bhagavatam texts.

Rate limits: 5 RPM, 250K tokens/minute
Strategy:   Batch 10 verses per request → ~30 batches/min well within limits
"""

import json
import logging
import os
import time
import re
from typing import Optional
from dotenv import load_dotenv

from google import genai
from google.genai import types as genai_types

load_dotenv()

logger = logging.getLogger(__name__)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = "gemini-3.1-flash-lite"

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert scholar of Vaishnava texts (Srimad-Bhagavatam, Caitanya-caritamrta, Caitanya Bhagavata).

Analyze the provided verse(s) and extract structured information.

Return ONLY a valid JSON object (no markdown, no extra text) with this exact structure:

{
  "entities": [
    {
      "name": "canonical English name",
      "sanskrit_name": "Sanskrit/transliterated name if different",
      "type": one of ["person","deva","demon","sage","place","river","mountain","kingdom","dynasty","concept","object","text","animal"],
      "description": "1-2 sentence description",
      "aliases": ["alt name 1", "alt name 2"]
    }
  ],
  "relationships": [
    {
      "source": "entity name",
      "target": "entity name",
      "type": one of ["father_of","mother_of","son_of","daughter_of","brother_of","sister_of","spouse_of","disciple_of","guru_of","friend_of","enemy_of","incarnation_of","expansion_of","devotee_of","resident_of","king_of","killed_by","blessed_by","cursed_by"],
      "context": "brief explanation from the text"
    }
  ],
  "verse_summaries": [
    {
      "reference": "e.g. SB 1.1.1",
      "entities_mentioned": [
        {
          "name": "entity name",
          "source": "verse or purport"
        }
      ]
    }
  ]
}

Rules:
- Only extract entities clearly mentioned or unambiguously implied in the text
- Use canonical English names (e.g. "Krishna" not "Krsna" or "Kṛṣṇa") for the name field
- Put the full diacritic transliteration in sanskrit_name
- Include well-known aliases (e.g. aliases of Krishna: ["Govinda","Madhusudana","Vasudeva"])
- For relationships, only include those explicitly stated or strongly implied in the text
- Track whether each entity is mentioned in the verse translation ("verse") or the purport explanation ("purport")
- If nothing can be confidently extracted, return {"entities": [], "relationships": [], "verse_summaries": []}
"""


def _build_verse_block(verse: dict) -> str:
    """Format a single verse dict into a readable block for the prompt."""
    ref = verse.get("full_reference", "")
    translation = verse.get("translation", "")
    purport = (verse.get("purport_text") or "")[:1000]  # cap purport to 1000 chars
    block = f"[{ref}]\nTranslation: {translation}"
    if purport:
        block += f"\nPurport (excerpt): {purport}"
    return block


def extract_from_verses(verses: list[dict]) -> dict:
    """
    Call Gemini to extract entities and relationships from a batch of verses.
    
    Args:
        verses: list of verse dicts with keys: full_reference, translation, purport_text
    
    Returns:
        dict with keys: entities, relationships, verse_summaries
    """
    verse_blocks = "\n\n---\n\n".join(_build_verse_block(v) for v in verses)
    prompt = f"{SYSTEM_PROMPT}\n\nVERSES TO ANALYZE:\n\n{verse_blocks}"

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        raw = response.text.strip()
        # Strip any accidental markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nRaw: {response.text[:500]}")
        return {"entities": [], "relationships": [], "verse_summaries": []}
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return {"entities": [], "relationships": [], "verse_summaries": []}


def extract_with_retry(verses: list[dict], max_retries: int = 5) -> dict:
    """Call extract_from_verses with exponential backoff on rate-limit and 500 errors."""
    for attempt in range(max_retries):
        try:
            return extract_from_verses(verses)
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = "429" in err_str or "quota" in err_str or "rate" in err_str
            is_server_error = "500" in err_str or "internal" in err_str
            
            if is_rate_limit or is_server_error:
                wait = 15 * (2 ** attempt)  # 15s, 30s, 60s, 120s, 240s
                error_type = "rate limit" if is_rate_limit else "server error"
                logger.warning(f"{error_type.title()} hit, waiting {wait}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed after {max_retries} retries: {e}")
                raise
    
    return {"entities": [], "relationships": [], "verse_summaries": []}
    logger.error("Max retries exceeded")
    return {"entities": [], "relationships": [], "verse_summaries": []}
