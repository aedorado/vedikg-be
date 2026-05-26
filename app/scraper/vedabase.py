import httpx
import logging
import asyncio
import re
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from urllib.parse import urljoin
from sqlalchemy.orm import Session
from app.db.base import SessionLocal
from app.models.models import (
    Canto, Chapter, Verse, Entity, VerseEntity, ScrapeJob, Relationship,
    ScrapeStatus, MentionLocation, RelationshipType
)
from app.nlp.alias_resolver import (
    resolve_alias, 
    get_all_known_entities,
    ALIAS_TO_ENTITY
)
from app.nlp.relationship_extractor import RelationshipExtractor
from app.nlp.chanda_detector import detect_chanda, detect_chanda_detail
import json as _json

logger = logging.getLogger(__name__)

# Initialize relationship extractor
rel_extractor = RelationshipExtractor()

# ── Entity type inference ─────────────────────────────────────────────────────
_KNOWN_PLACES = {
    # Upper lokas
    'bhūloka', 'bhuvarloka', 'svargaloka', 'svarga', 'maharloka',
    'janaloka', 'tapoloka', 'satyaloka', 'brahmaloka', 'devaloka',
    'vaikuṇṭha', 'vaikuṇṭhaloka', 'kailāsa', 'pitṛloka',
    # Lower / hellish lokas
    'atala', 'vitala', 'sutala', 'talātala', 'mahātala', 'rasātala', 'pātāla',
    'naraka',
    # 28 hellish planets (SB 5.26)
    'tāmisra', 'andhatāmisra', 'raurava', 'mahāraurava', 'kumbhīpāka',
    'kālasūtra', 'asipatravana', 'sūkaramukha', 'andhakūpa', 'kṛmibhojana',
    'sandaṁśa', 'taptasūrmi', 'vajrakaṇṭaka-śālmalī', 'vaitaraṇī', 'pūyoda',
    'prāṇarodha', 'viśasana', 'lālābhakṣa', 'sārameyādana', 'avīci', 'avīcimat',
    'ayaḥpāna', 'kṣārakardama', 'rakṣogaṇa-bhojana', 'śūlaprota', 'dandaśūka',
    'avaṭa-nirodhana', 'paryāvartana', 'sūcīmukha',
    # Cosmological
    'bhū-maṇḍala', 'bhūmaṇḍala', 'garbhodaka', 'jambūdvīpa',
    # Sacred/geographic places
    'naimiṣāraṇya', 'vṛndāvana', 'mathurā', 'dvārakā', 'kurukṣetra',
    'hastināpura', 'indraprastha', 'ayodhyā', 'laṅkā', 'kiṣkindhā',
    'prabhāsa', 'prayāga', 'kāśī', 'vārāṇasī', 'badarikāśrama', 'badarī',
    'puṣkara', 'bharata-varṣa',
}
_PLACE_SUFFIXES = ('loka', 'pura', 'nagara', 'kṣetra', 'tala', 'vana', 'āvarta', 'dvīpa')
_RIVER_NAMES = {
    'gaṅgā', 'yamunā', 'sarasvatī', 'narmadā', 'godāvarī', 'sindhu',
    'kālindī', 'kāverī', 'vaitaraṇī',
}

# Person names that happen to end with place-like suffixes — force as 'person'
_PERSON_NAME_OVERRIDES = {
    # -vana endings
    'cyavana', 'bhavana', 'marudvana', 'yavana', 'jīvana',
    # -loka endings (śloka = hymn/verse, not a planetary system)
    'uttamaśloka', 'uttamaḥśloka', 'upaśloka', 'śloka',
    # misc
    'nara', 'sthāna', 'nagara', 'nārada', 'rāghava',
}

# Ethnic groups / peoples — person-type, not places
_ETHNIC_GROUPS = {
    'yavana', 'kirāta', 'hūṇa', 'pulinda', 'pulkaśa', 'ābhīra', 'śumbha',
    'khasa', 'mleccha', 'āndhra', 'niṣāda',
}

def _infer_entity_type(name: str) -> str:
    nl = name.lower()
    if nl in _PERSON_NAME_OVERRIDES or nl in _ETHNIC_GROUPS:
        return 'person'
    if nl in _KNOWN_PLACES:
        return 'place'
    if nl in _RIVER_NAMES:
        return 'river'
    for suf in _PLACE_SUFFIXES:
        if nl.endswith(suf):
            # 'śloka' ends with 'loka' but means verse/hymn — not a planetary system
            if suf == 'loka' and nl.endswith('śloka'):
                continue
            return 'place'
    return 'person'

# Get all known entities (dynamic from alias resolver)
KNOWN_ENTITY_NAMES = {
    entity: "person" for entity in get_all_known_entities()
}

# Legacy - kept for reference but not used
MAJOR_ENTITIES = {
    "Krishna": "person",
    "Arjuna": "person",
    "Brahma": "person",
    "Shiva": "person",
    "Vishnu": "person",
    "Narada": "sage",
    "Vyasa": "sage",
    "Sukadeva": "sage",
    "Parikshit": "person",
    "Dhruva": "person",
    "Prahlada": "person",
    "Hiranyakashipu": "demon",
    "Vasudeva": "person",
    "Devaki": "person",
    "Kunti": "person",
    "Draupadi": "person",
    "Pandavas": "person",
    "Kauravas": "person",
    "Kurus": "person",
    "Bhima": "person",
    "Yudhishthira": "person",
    "Indra": "deva",
    "Surya": "deva",
    "Chandra": "deva",
    "Atri": "sage",
    "Anusuya": "person",
    "Buddha": "person",
    "Pariksit": "person",
    "Janamejaya": "person",
    "Yudhamanyu": "person",
    "Uttamaujas": "person",
    "Dhritarashtra": "person",
    "Gandhari": "person",
    "Shakuni": "person",
    "Karna": "person",
    "Duryodhana": "person",
    "Dushasana": "person",
    "Ashvatthama": "person",
    "Dronacharya": "person",
    "Bhishma": "person",
    "Satyaki": "person",
    "Abhimanyu": "person",
    "Ghatotkacha": "person",
    "Draupadi": "person",
    "Subhadra": "person",
    "Rukmini": "person",
    "Kamsa": "demon",
    "Jarasandha": "demon",
    "Shalva": "demon",
    "Dantavakra": "demon",
}


class VedabaseScraper:
    def __init__(self, base_url: str = "https://vedabase.io"):
        self.base_url = base_url
        self.timeout = 30.0
        self.retry_attempts = 3
        self.retry_delay = 2.0

    async def scrape_chapters(self, canto_num: int, chapters: List[int], db: Session):
        """Scrape specific chapters and save to database.
        
        Args:
            canto_num: Canto number (1-18)
            chapters: List of chapter numbers to scrape
            db: Database session
        """
        logger.info(f"Starting scrape: SB {canto_num}.{chapters}")
        
        for chapter_num in chapters:
            try:
                await self._scrape_chapter(canto_num, chapter_num, db)
            except Exception as e:
                logger.error(f"Failed to scrape SB {canto_num}.{chapter_num}: {e}")
                continue

    async def _scrape_chapter(self, canto_num: int, chapter_num: int, db: Session):
        """Scrape a single chapter."""
        logger.info(f"Scraping SB {canto_num}.{chapter_num}...")
        
        # Get or create chapter record
        canto = self._get_or_create_canto(db, canto_num)
        chapter = self._get_or_create_chapter(db, canto.id, chapter_num)
        
        # Fetch chapter index to find all verses
        chapter_url = f"{self.base_url}/en/library/sb/{canto_num}/{chapter_num}/"
        verse_urls = await self._discover_verses(chapter_url)
        
        logger.info(f"Found {len(verse_urls)} verses in SB {canto_num}.{chapter_num}")
        
        # Scrape each verse
        for verse_num, verse_url in enumerate(verse_urls, 1):
            try:
                await self._scrape_verse(db, chapter, verse_num, verse_url)
                
                # Save checkpoint after each verse
                db.commit()
                logger.info(f"✓ SB {canto_num}.{chapter_num}.{verse_num}")
                
            except Exception as e:
                logger.error(f"Error scraping verse {verse_num}: {e}")
                db.rollback()
                continue
        
        logger.info(f"✓ Completed SB {canto_num}.{chapter_num}")

    async def _discover_verses(self, chapter_url: str) -> List[str]:
        """Discover all verse URLs in a chapter."""
        html = await self._fetch_url(chapter_url)
        if not html:
            return []
        
        soup = BeautifulSoup(html, "html.parser")
        verse_links = []
        
        # Find all verse links (pattern: Text 1, Text 2, etc.)
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            # Look for verse pattern: /sb/{c}/{ch}/{v}/
            if re.match(r"/en/library/sb/\d+/\d+/\d+/?$", href):
                verse_url = urljoin(self.base_url, href)
                if verse_url not in verse_links:
                    verse_links.append(verse_url)
        
        return verse_links

    async def _scrape_verse(self, db: Session, chapter: Chapter, verse_num: int, verse_url: str):
        """Scrape a single verse and save to database."""
        logger.debug(f"Fetching {verse_url}")
        html = await self._fetch_url(verse_url)
        if not html:
            logger.debug(f"No HTML returned for verse {verse_num}")
            return
        
        logger.info(f"Parsing verse {verse_num}")
        verse_data = self._parse_verse(html, verse_url)
        if not verse_data:
            logger.info(f"No verse data parsed for verse {verse_num}")
            return
        
        logger.info(f"Creating database record for verse {verse_num}")
        # Skip if this verse was already scraped
        full_ref = f"SB {chapter.canto.number}.{chapter.chapter_number}.{verse_num}"
        existing_verse = db.query(Verse).filter_by(full_reference=full_ref).first()
        if existing_verse:
            logger.info(f"Verse {full_ref} already in DB, skipping")
            return

        # Create verse record
        verse = Verse(
            chapter_id=chapter.id,
            verse_number=verse_num,
            full_reference=full_ref,
            source_url=verse_url,
            devanagari=verse_data.get("devanagari", ""),
            transliteration=verse_data.get("transliteration", ""),
            translation=verse_data.get("translation", ""),
            synonyms_raw=verse_data.get("synonyms", ""),
            purport_html=verse_data.get("purport_html", ""),
            purport_text=verse_data.get("purport_text", ""),
            chanda=detect_chanda(verse_data.get("transliteration", "")),
            chanda_json=_json.dumps(detect_chanda_detail(verse_data.get("transliteration", "")), ensure_ascii=False) if verse_data.get("transliteration") else None,
            scraped_at=datetime.utcnow(),
        )
        db.add(verse)
        db.flush()
        
        logger.debug(f"Extracting entities for verse {verse_num}")
        # Extract and link entities
        self._extract_and_link_entities(db, verse, verse_data)

    def _parse_verse(self, html: str, url: str) -> Optional[Dict]:
        """Parse verse HTML - extract verse data and purport."""
        try:
            soup = BeautifulSoup(html, "html.parser")
            
            data = {
                "devanagari": "",
                "transliteration": "",
                "translation": "",
                "synonyms": "",
                "purport_html": "",
                "purport_text": "",
            }
            
            # Remove script, style, header/nav/footer tags
            for tag in soup(["script", "style", "header", "nav", "footer", "iframe"]):
                tag.decompose()

            # ── Structured sections via vedabase CSS classes ──────────────────
            # Helper: extract text from a section div, stripping its h2 heading
            def _section_text(div, separator="\n"):
                if not div:
                    return ""
                for h2 in div.find_all('h2'):
                    h2.decompose()
                return div.get_text(separator=separator, strip=True)

            # Devanagari script  (av-devanagari)
            deva_div = soup.find(class_="av-devanagari")
            if deva_div:
                data["devanagari"] = _section_text(deva_div)

            # IAST Roman transliteration  (av-verse_text — NOT devanagari!)
            iast_div = soup.find(class_="av-verse_text")
            if iast_div:
                data["transliteration"] = _section_text(iast_div)

            # Synonyms (word-by-word)
            syn_div = soup.find(class_="av-synonyms")
            if syn_div:
                data["synonyms"] = _section_text(syn_div, separator=" ")

            # Translation (prefer dedicated div; fall back to text scan below)
            trans_div = soup.find(class_="av-translation")
            if trans_div:
                raw_trans = _section_text(trans_div, separator=" ")
                data["translation"] = raw_trans

            # ── Purport ───────────────────────────────────────────────────────
            purport_div = soup.find(class_="av-purport")
            if purport_div:
                # Clone before stripping h2 for HTML storage
                import copy
                purport_clone = copy.copy(purport_div)
                for h2 in purport_div.find_all('h2'):
                    h2.decompose()
                data["purport_html"] = str(purport_div)
                data["purport_text"] = purport_div.get_text(separator="\n", strip=True)
            
            # ── Fallback: plain-text scan if CSS classes weren't found ────────
            if not data["translation"]:
                main = soup.find("main") or soup.find("article") or soup.body
                if not main:
                    return None
                
                full_text = main.get_text(separator="\n", strip=True)
                
                if not full_text or len(full_text) < 100:
                    return None
                
                # Split on "Purport" to isolate verse content
                verse_content = full_text.split("Purport", 1)[0].strip() if "Purport" in full_text else full_text
                
                if "Translation" in verse_content:
                    trans_idx = verse_content.index("Translation")
                    translation = verse_content[trans_idx + 11:].strip()[:10000]
                else:
                    translation = verse_content[:5000]

                # Strip vedabase navigation text that leaks in
                translation = re.sub(
                    r'(\s*\n\s*|\s+)Texts?\s+[\d\-]+(?:\s*\n\s*Texts?\s+[\d\-]+)*\s*$',
                    '', translation, flags=re.IGNORECASE
                ).strip()
                data["translation"] = translation
                
                # Fallback purport_text if .av-purport not found
                if not data["purport_text"] and "Purport" in full_text:
                    data["purport_text"] = full_text.split("Purport", 1)[1].strip()[:100000]

            # Strip nav leak from translation regardless of source
            if data["translation"]:
                data["translation"] = re.sub(
                    r'(\s*\n\s*|\s+)Texts?\s+[\d\-]+(?:\s*\n\s*Texts?\s+[\d\-]+)*\s*$',
                    '', data["translation"], flags=re.IGNORECASE
                ).strip()
            
            return data if any([data["translation"], data["purport_text"]]) else None
            
        except Exception as e:
            logger.error(f"Parse error for {url}: {e}")
            return None

    def _extract_and_link_entities(self, db: Session, verse: Verse, verse_data: Dict):
        """Extract entity mentions and relationships using NLP-based approach."""
        verse_text = verse_data.get("translation", "") or ""
        purport_text = verse_data.get("purport_text", "") or ""
        combined_text = verse_text + "\n" + purport_text

        found_entities = rel_extractor.extract_all_entities(combined_text)

        found_entity_ids = {}

        for entity_name in found_entities:
            verse_mention = self._find_mention(entity_name, verse_text)
            purport_mention = self._find_mention(entity_name, purport_text)

            entity = db.query(Entity).filter_by(normalized_name=entity_name.lower()).first()
            if not entity:
                entity = Entity(
                    name=entity_name,
                    normalized_name=entity_name.lower(),
                    entity_type=_infer_entity_type(entity_name),
                )
                db.add(entity)
                db.flush()

            found_entity_ids[entity_name] = entity.id

            if verse_mention and purport_mention:
                location, mention_text = "both", verse_mention
            elif verse_mention:
                location, mention_text = "verse_text", verse_mention
            elif purport_mention:
                location, mention_text = "purport_text", purport_mention
            else:
                continue

            # Avoid duplicate verse_entity rows
            existing_ve = db.query(VerseEntity).filter_by(
                verse_id=verse.id, entity_id=entity.id
            ).first()
            if not existing_ve:
                db.add(VerseEntity(
                    verse_id=verse.id,
                    entity_id=entity.id,
                    mention_location=location,
                    mention_text=mention_text[:200],
                    confidence_score=0.95,
                ))

        # ── Relationships ─────────────────────────────────────────────────────
        relationships = rel_extractor.extract_relationships(combined_text)

        for entity1_name, entity2_name, rel_type in relationships:
            # Ensure both entities exist (they may be newly discovered via rel patterns)
            for name in (entity1_name, entity2_name):
                if name not in found_entity_ids:
                    ent = db.query(Entity).filter_by(normalized_name=name.lower()).first()
                    if not ent:
                        ent = Entity(
                            name=name,
                            normalized_name=name.lower(),
                            entity_type=_infer_entity_type(name),
                        )
                        db.add(ent)
                        db.flush()
                    found_entity_ids[name] = ent.id

            e1_id = found_entity_ids.get(entity1_name)
            e2_id = found_entity_ids.get(entity2_name)
            if not e1_id or not e2_id:
                continue

            rel_type_val = self._map_relationship_type(rel_type)
            if not rel_type_val:
                continue

            # Avoid duplicate relationships
            existing_rel = db.query(Relationship).filter_by(
                source_entity_id=e1_id,
                target_entity_id=e2_id,
                relationship_type=rel_type_val,
            ).first()
            if not existing_rel:
                db.add(Relationship(
                    source_entity_id=e1_id,
                    target_entity_id=e2_id,
                    relationship_type=rel_type_val,
                    source_verse_id=verse.id,
                    confidence_score=0.85,
                ))
                logger.debug(f"  ↳ {entity1_name} —{rel_type}→ {entity2_name}")

        logger.debug(f"  entities={len(found_entities)} rels={len(relationships)}")
    
    def _map_relationship_type(self, rel_type_str: str) -> Optional[str]:
        """Map relationship string to RelationshipType enum value."""
        mapping = {
            "father_of": "father_of",
            "mother_of": "mother_of",
            "son_of": "son_of",
            "daughter_of": "daughter_of",
            "brother_of": "brother_of",
            "sister_of": "sister_of",
            "spouse_of": "spouse_of",
        }
        return mapping.get(rel_type_str)


    def _find_mention(self, entity_name: str, text: str) -> Optional[str]:
        """Find entity mention in text with context, checking all aliases."""
        if not text:
            return None
        
        # Get all aliases for this entity
        from app.nlp.alias_resolver import get_aliases_for_entity
        aliases = get_aliases_for_entity(entity_name)
        
        text_lower = text.lower()
        
        # Check each alias
        for alias in aliases:
            alias_lower = alias.lower()
            idx = text_lower.find(alias_lower)
            if idx != -1:
                # Extract context (50 chars before and after)
                start = max(0, idx - 50)
                end = min(len(text), idx + len(alias) + 50)
                return text[start:end].strip()
        
        # Fallback to entity name if not found in aliases
        entity_lower = entity_name.lower()
        idx = text_lower.find(entity_lower)
        if idx == -1:
            return None
        
        # Extract context (50 chars before and after)
        start = max(0, idx - 50)
        end = min(len(text), idx + len(entity_name) + 50)
        
        return text[start:end].strip()

    async def _fetch_url(self, url: str, attempt: int = 1) -> Optional[str]:
        """Fetch URL with retry logic."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.debug(f"Fetching attempt {attempt}: {url}")
                response = await client.get(url)
                response.raise_for_status()
                logger.debug(f"Successfully fetched {url}")
                return response.text
        except Exception as e:
            if attempt < self.retry_attempts:
                logger.warning(f"Fetch failed (attempt {attempt}), retrying in {self.retry_delay}s: {url}")
                await asyncio.sleep(self.retry_delay)
                return await self._fetch_url(url, attempt + 1)
            else:
                logger.error(f"Failed to fetch {url} after {self.retry_attempts} attempts")
                return None

    def _get_or_create_canto(self, db: Session, canto_num: int) -> Canto:
        """Get or create canto record."""
        canto = db.query(Canto).filter_by(number=canto_num).first()
        if not canto:
            canto = Canto(
                number=canto_num,
                title=f"Canto {canto_num}",
                slug=f"canto-{canto_num}",
            )
            db.add(canto)
            db.flush()
        return canto

    def _get_or_create_chapter(self, db: Session, canto_id: int, chapter_num: int) -> Chapter:
        """Get or create chapter record."""
        chapter = db.query(Chapter).filter_by(
            canto_id=canto_id, 
            chapter_number=chapter_num
        ).first()
        if not chapter:
            chapter = Chapter(
                canto_id=canto_id,
                chapter_number=chapter_num,
                title=f"Chapter {chapter_num}",
                slug=f"chapter-{chapter_num}",
            )
            db.add(chapter)
            db.flush()
        return chapter

    async def scrape_sample(self):
        """Scrape SB 1.1-5 (Chapters 1-5, ~250 verses) as sample."""
        db = SessionLocal()
        try:
            await self.scrape_chapters(canto_num=1, chapters=[1, 2, 3, 4, 5], db=db)
            logger.info("✓ Sample scrape (SB 1.1-5) completed successfully")
        except Exception as e:
            logger.error(f"Sample scrape failed: {e}")
            db.rollback()
        finally:
            db.close()
