"""
Detect Sanskrit meter (chanda) from IAST transliteration text.
Returns the primary meter name in Devanagari (e.g. 'अनुष्टुभ्', 'शार्दूलविक्रीडित').
"""

from __future__ import annotations
import re
import json

# ── Bengali prose markers in IAST transliteration ────────────────────────────
# These words appear in Bengali-language verses but NEVER in Sanskrit verses.
# Two or more hits → language='bn', skip chandas detection.
_BENGALI_MARKERS = {
    # verbs / verbal forms
    'kahe', 'bale', 'kahilā', 'kahila', 'bolilā', 'bolila', 'bolena',
    'hailā', 'haila', 'haye', 'haiyā', 'āche', 'āchena', 'āchila',
    'dekhiyā', 'śuniyā', 'kariyā', 'lañā', 'diyā', 'niyā',
    # pronouns / postpositions
    'āmāra', 'āmāre', 'āmā', 'tomāra', 'tomāre', 'tomā',
    'tāhāṅ', 'tāṅhā', 'sethā', 'yathā',
    # adverbs / particles
    'yāñā', 'yāite', 'calaha', 'āisa', 'āilā',
    'kibā', 'tabe', 'kintu', 'sabe', 'sabāra',
}

def detect_language(transliteration: str) -> str:
    """Detect language of a CC verse from its IAST transliteration.

    Returns 'sa' (Sanskrit) or 'bn' (Bengali).
    Uses Bengali-specific function words that never appear in Sanskrit.
    This is needed because CC encodes ALL verses in Bengali script —
    the script alone cannot distinguish language.
    """
    if not transliteration:
        return 'sa'
    words = set(re.findall(r"[a-zA-ZāīūṛṜṝṄṅṇṭḍśṣḥṃĀĪŪṬḌŚṢĀĪŪ']+",
                           transliteration.lower()))
    hits = words & _BENGALI_MARKERS
    return 'bn' if len(hits) >= 2 else 'sa'


_chanda_instance = None


def _get_chanda():
    global _chanda_instance
    if _chanda_instance is None:
        from chanda import Chanda
        _chanda_instance = Chanda()
    return _chanda_instance


def _strip_speaker_lines(text: str) -> str:
    """Remove speaker attribution lines like 'śrī-bhīṣma uvāca', 'sūta uvāca', etc."""
    import re
    lines = text.splitlines()
    filtered = [l for l in lines if not re.search(r'\buvāca\b', l, re.IGNORECASE)]
    return "\n".join(filtered).strip()


def _normalize_meter_name(name: str) -> str:
    """Normalize compound meter names like 'X = Y' → 'Y', and known aliases."""
    if not name:
        return name
    # "औपच्छन्दसिक = पुष्पिताग्रा" → "पुष्पिताग्रा"
    if " = " in name:
        name = name.split(" = ")[-1].strip()
    ALIASES = {
        "वक्त्र": "अनुष्टुभ्",
        "मृगेन्द्रमुख": "पुष्पिताग्रा",  # same meter, different name in library
    }
    return ALIASES.get(name, name)


def detect_chanda(iast_text: str) -> str | None:
    """Return the dominant meter name for a verse, or None if unknown."""
    result = detect_chanda_detail(iast_text)
    return result.get("name") if result else None


def detect_chanda_detail(iast_text: str) -> dict | None:
    """Return full chanda analysis: name, jaati, per-line breakdown."""
    if not iast_text or not iast_text.strip():
        return None
    try:
        c = _get_chanda()
        cleaned = _strip_speaker_lines(iast_text)
        if not cleaned:
            return None
        result = c.analyze_text(cleaned, fuzzy=True)
        d = result.to_dict()

        names: list[str] = []
        for entry in d["result"].get("verse", []):
            if isinstance(entry, (list, tuple)) and entry:
                name = entry[0]
                if name and "उपजाति" not in name:
                    names.append(_normalize_meter_name(name))

        lines_detail = []
        for line_obj in d["result"].get("line", []):
            lr = line_obj["result"]
            line_chandas = [_normalize_meter_name(n) for n, _ in lr.get("chanda", []) if n and "उपजाति" not in n]
            line_jaati   = lr.get("jaati", [])
            line_text    = lr.get("line", "")
            syllables    = lr.get("length", 0)
            gana         = lr.get("gana", "")
            for n in line_chandas:
                names.append(n)
            lines_detail.append({
                "line": line_text,
                "chanda": line_chandas[0] if line_chandas else None,
                "jaati": line_jaati[0] if line_jaati else None,
                "syllables": syllables,
                "gana": gana,
            })

        from collections import Counter

        # PRIMARY: majority vote on exact names
        name_counts = Counter(names)
        top_name, top_count = name_counts.most_common(1)[0] if name_counts else (None, 0)
        total_named = sum(name_counts.values())
        primary_clear = top_count > total_named / 2 or len(name_counts) <= 1

        # SECONDARY: fuzzy names from lines that have no exact chanda
        fuzzy_names = []
        for line_obj in d["result"].get("line", []):
            lr = line_obj["result"]
            if lr.get("chanda"):
                continue  # already have exact for this line
            fuzzy_matches = lr.get("fuzzy", [])
            if fuzzy_matches:
                first_fuzzy = fuzzy_matches[0]
                if isinstance(first_fuzzy, dict):
                    fuzzy_chandas = first_fuzzy.get("chanda", [])
                    if fuzzy_chandas:
                        fuzzy_names.append(_normalize_meter_name(fuzzy_chandas[0][0]))

        if primary_clear and top_name:
            name = top_name
        else:
            # Combine exact + fuzzy to resolve tie or no exact match
            combined = Counter(names) + Counter(fuzzy_names)
            if combined:
                name = combined.most_common(1)[0][0]
            elif fuzzy_names:
                name = Counter(fuzzy_names).most_common(1)[0][0]
            else:
                name = "अनुष्टुभ्" if "अनुष्टुभ्" in name_counts else top_name
        
        # TERTIARY: Fallback to jaati if still no name
        jaati_names = [l["jaati"] for l in lines_detail if l["jaati"]]
        jaati = Counter(jaati_names).most_common(1)[0][0] if jaati_names else None
        if not name:
            name = jaati

        return {
            "name": name,
            "jaati": jaati,
            "lines": lines_detail,
            "raw": d,
        }
    except Exception:
        return None
