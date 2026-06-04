import httpx
import logging
import asyncio
import re
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Optional, Dict, List
from urllib.parse import urljoin
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.db.base import SessionLocal
from app.models.models import Canto, Chapter, Verse, Purport, Author
from app.nlp.chanda_detector import detect_chanda, detect_chanda_detail
import json as _json

logger = logging.getLogger(__name__)


class VedabaseScraper:
    def __init__(self, base_url: str = "https://vedabase.io"):
        self.base_url = base_url
        self.timeout = 30.0
        self.retry_attempts = 3
        self.retry_delay = 2.0

    async def scrape_chapters(self, canto_num: int, chapters: List[int],
                              concurrency: int = 5):
        """Scrape chapters concurrently (default 5 at a time), each with its own DB session."""
        logger.info(f"Starting scrape: SB {canto_num} chapters {chapters[0]}–{chapters[-1]} "
                    f"(concurrency={concurrency})")
        sem = asyncio.Semaphore(concurrency)

        async def _scrape_with_sem(chapter_num: int):
            async with sem:
                chapter_db = SessionLocal()
                try:
                    await self._scrape_chapter(canto_num, chapter_num, chapter_db)
                except Exception as e:
                    logger.error(f"Failed to scrape SB {canto_num}.{chapter_num}: {e}")
                finally:
                    chapter_db.close()

        await asyncio.gather(*[_scrape_with_sem(ch) for ch in chapters])

    async def _scrape_chapter(self, canto_num: int, chapter_num: int, db: Session):
        """Scrape a single chapter — fetch all verses concurrently, bulk insert once."""
        logger.info(f"Scraping SB {canto_num}.{chapter_num}...")

        chapter_url = f"{self.base_url}/en/library/sb/{canto_num}/{chapter_num}/"
        chapter_html = await self._fetch_url(chapter_url)
        if not chapter_html:
            logger.error(f"Could not fetch chapter page {chapter_url}")
            return

        chapter_meta = self._parse_chapter_meta(chapter_html, canto_num, chapter_num)
        canto = self._get_or_create_canto(db, canto_num, chapter_meta.get("canto_title"))
        chapter = self._get_or_create_chapter(
            db, canto.id, chapter_num,
            title=chapter_meta.get("chapter_title"),
            summary=chapter_meta.get("chapter_summary"),
            source_url=chapter_url,
        )
        db.commit()

        verse_urls = self._extract_verse_urls(chapter_html, chapter_url)
        logger.info(f"Found {len(verse_urls)} verse URLs in SB {canto_num}.{chapter_num}")
        if not verse_urls:
            return

        # Fetch all verse pages concurrently
        htmls = await asyncio.gather(*[self._fetch_url(url) for url in verse_urls])

        # Resolve Prabhupāda's author_id once per chapter
        prabhupada = db.query(Author).filter_by(slug="srila-prabhupada").first()
        prabhupada_id = prabhupada.id if prabhupada else None

        # Parse in memory — no DB touches yet
        rows = []       # verse dicts
        purports = []   # (full_reference, purport_html, purport_text) for purports table
        now = datetime.utcnow()
        for verse_url, html in zip(verse_urls, htmls):
            if not html:
                continue
            verse_data = self._parse_verse(html, verse_url)
            if not verse_data:
                continue

            full_ref = verse_data.get("full_reference") or \
                       f"SB {canto_num}.{chapter_num}.{self._verse_num_from_url(verse_url, chapter_num)}"
            m = re.search(r'\.(\d+)(?:-\d+)?$', full_ref)
            ref_verse_num = int(m.group(1)) if m else self._verse_num_from_url(verse_url, chapter_num)
            transliteration = verse_data.get("transliteration", "")
            rows.append(dict(
                chapter_id=chapter.id,
                verse_number=ref_verse_num,
                full_reference=full_ref,
                source_url=verse_url,
                devanagari=verse_data.get("devanagari", ""),
                transliteration=transliteration,
                translation=verse_data.get("translation", ""),
                synonyms_raw=verse_data.get("synonyms", ""),
                chanda=detect_chanda(transliteration),
                chanda_json=_json.dumps(detect_chanda_detail(transliteration), ensure_ascii=False) if transliteration else None,
                scraped_at=now,
            ))
            if verse_data.get("purport_html") or verse_data.get("purport_text"):
                purports.append((
                    full_ref,
                    verse_data.get("purport_html", ""),
                    verse_data.get("purport_text", ""),
                ))

        if not rows:
            logger.warning(f"No verses parsed for SB {canto_num}.{chapter_num}")
            return

        # Skip already-scraped verses
        existing_refs = {
            r[0] for r in db.query(Verse.full_reference)
            .filter(Verse.full_reference.in_([r["full_reference"] for r in rows]))
            .all()
        }
        new_rows = [r for r in rows if r["full_reference"] not in existing_refs]

        if not new_rows:
            logger.info(f"✓ SB {canto_num}.{chapter_num} — all {len(rows)} verses already in DB")
            return

        db.execute(Verse.__table__.insert(), new_rows)
        db.flush()

        # Bulk insert purports linked to newly inserted verse ids
        if purports and prabhupada_id:
            new_refs = {r["full_reference"] for r in new_rows}
            ref_to_id = {
                ref: vid for ref, vid in
                db.query(Verse.full_reference, Verse.id)
                .filter(Verse.full_reference.in_(new_refs))
                .all()
            }
            purport_rows = [
                dict(verse_id=ref_to_id[ref], author_id=prabhupada_id,
                     body_html=html, body_text=text, language="en")
                for ref, html, text in purports
                if ref in ref_to_id and (html or text)
            ]
            if purport_rows:
                db.execute(Purport.__table__.insert(), purport_rows)

        db.commit()
        logger.info(f"✓ SB {canto_num}.{chapter_num} — inserted {len(new_rows)} verses, "
                    f"{len(purport_rows) if purports and prabhupada_id else 0} purports "
                    f"(skipped {len(rows) - len(new_rows)} existing)")

    def _verse_num_from_url(self, verse_url: str, chapter_num: int) -> int:
        """Extract starting verse number from URL like .../sb/10/14/8/ or .../sb/10/14/8-9/"""
        m = re.search(r'/sb/\d+/\d+/(\d+)', verse_url)
        if m:
            return int(m.group(1))
        return 0

    def _extract_verse_urls(self, html: str, chapter_url: str) -> List[str]:
        """Extract verse URLs from already-fetched chapter HTML."""
        soup = BeautifulSoup(html, "html.parser")
        verse_links = []
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if re.match(r"/en/library/sb/\d+/\d+/[\d\-]+/?$", href):
                verse_url = urljoin(self.base_url, href)
                if verse_url not in verse_links:
                    verse_links.append(verse_url)
        return verse_links

    def _parse_chapter_meta(self, html: str, canto_num: int, chapter_num: int) -> dict:
        """Parse chapter title and canto title from the vedabase RSC payload."""
        meta = {}

        # vedabase is a Next.js app that embeds data in RSC payload chunks.
        # The chunk containing page props has: "chapter_title":"Questions by the Sages"
        # Payload uses escaped quotes: chapter_title\":\"Questions by the Sages\"
        m = re.search(r'chapter_title\\":\\"([^\\"]+)\\"', html)
        if m:
            meta["chapter_title"] = m.group(1)

        # Canto breadcrumb: "Canto 1: Creation\\"
        m = re.search(rf'Canto\s+{canto_num}:\s*([^\\"]+)\\"', html)
        if m:
            meta["canto_title"] = f"Canto {canto_num}: {m.group(1).strip()}"

        # Chapter summary: text in em-mb-4 divs before the first "Text 1:" link
        # The page renders content twice (SSR + RSC), so deduplicate by seen set
        soup = BeautifulSoup(html, "html.parser")
        summary_parts = []
        seen = set()
        for div in soup.find_all("div", class_=re.compile(r"em-mb-4")):
            a = div.find("a")
            if a and re.search(r"Text\s+1\b", a.get_text()):
                break
            text = div.get_text(" ", strip=True)
            if len(text) > 80 and text not in seen:
                seen.add(text)
                summary_parts.append(text)
        if summary_parts:
            meta["chapter_summary"] = "\n\n".join(summary_parts)

        return meta

    async def _discover_verses(self, chapter_url: str) -> List[str]:
        """Discover all verse URLs in a chapter (kept for backward compat)."""
        html = await self._fetch_url(chapter_url)
        if not html:
            return []
        return self._extract_verse_urls(html, chapter_url)

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
                "full_reference": None,
            }
            
            # Extract canonical reference from page (e.g. "SB 10.14.8" or "SB 10.14.8-9")
            # vedabase puts it in <title> or a canonical heading
            page_title = soup.find("title")
            if page_title:
                m = re.search(r'SB\s+(\d+\.\d+\.[\d\-]+)', page_title.get_text())
                if m:
                    data["full_reference"] = "SB " + m.group(1)
            if not data["full_reference"]:
                # Try og:title or canonical meta
                og = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "title"})
                if og:
                    m = re.search(r'SB\s+(\d+\.\d+\.[\d\-]+)', og.get("content", ""))
                    if m:
                        data["full_reference"] = "SB " + m.group(1)
            if not data["full_reference"]:
                # Fall back to URL
                m = re.search(r'/sb/(\d+)/(\d+)/([\d\-]+)/?$', url)
                if m:
                    data["full_reference"] = f"SB {m.group(1)}.{m.group(2)}.{m.group(3)}"

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

    async def _fetch_url(self, url: str, attempt: int = 1) -> Optional[str]:
        """Fetch URL with retry logic. 404s are not retried."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.debug(f"Fetching attempt {attempt}: {url}")
                response = await client.get(url)
                if response.status_code == 404:
                    logger.debug(f"404 — skipping {url}")
                    return None
                response.raise_for_status()
                return response.text
        except httpx.HTTPStatusError:
            # Already handled 404 above; other 4xx are not worth retrying
            return None
        except Exception as e:
            if attempt < self.retry_attempts:
                delay = self.retry_delay * (2 ** (attempt - 1))  # exponential backoff
                logger.warning(f"Fetch failed (attempt {attempt}/{self.retry_attempts}), retrying in {delay:.1f}s: {url}")
                await asyncio.sleep(delay)
                return await self._fetch_url(url, attempt + 1)
            else:
                logger.error(f"Failed to fetch {url} after {self.retry_attempts} attempts")
                return None

    def _get_or_create_canto(self, db: Session, canto_num: int, title: str = None) -> Canto:
        """Get or create canto record, safe under concurrent scrapers."""
        from app.models.models import Book
        sb_book = db.query(Book).filter_by(code='SB').first()
        if not sb_book:
            sb_book = Book(code='SB', title='Śrīmad-Bhāgavatam',
                           url_prefix='https://vedabase.io/en/library/sb/')
            db.add(sb_book)
            db.flush()
        canto = db.query(Canto).filter_by(book_id=sb_book.id, number=canto_num).first()
        if not canto:
            try:
                canto = Canto(
                    number=canto_num,
                    title=title or f"Canto {canto_num}",
                    slug=f"sb-canto-{canto_num}",
                    book_id=sb_book.id,
                )
                db.add(canto)
                db.flush()
            except IntegrityError:
                db.rollback()
                canto = db.query(Canto).filter_by(book_id=sb_book.id, number=canto_num).first()
        elif title and (not canto.title or canto.title == f"Canto {canto_num}"):
            canto.title = title
        return canto

    def _get_or_create_chapter(self, db: Session, canto_id: int, chapter_num: int,
                                title: str = None, summary: str = None, source_url: str = None) -> Chapter:
        """Get or create chapter record, safe under concurrent scrapers."""
        chapter = db.query(Chapter).filter_by(canto_id=canto_id, chapter_number=chapter_num).first()
        if not chapter:
            try:
                chapter = Chapter(
                    canto_id=canto_id,
                    chapter_number=chapter_num,
                    title=title or f"Chapter {chapter_num}",
                    slug=f"chapter-{chapter_num}",
                    summary=summary,
                    source_url=source_url,
                )
                db.add(chapter)
                db.flush()
            except IntegrityError:
                db.rollback()
                chapter = db.query(Chapter).filter_by(canto_id=canto_id, chapter_number=chapter_num).first()
        else:
            if title and (not chapter.title or chapter.title == f"Chapter {chapter_num}"):
                chapter.title = title
            if summary and not chapter.summary:
                chapter.summary = summary
            if source_url and not chapter.source_url:
                chapter.source_url = source_url
        return chapter

    async def scrape_sample(self):
        """Scrape SB 1.1-5 (Chapters 1-5, ~250 verses) as sample."""
        await self.scrape_chapters(canto_num=1, chapters=[1, 2, 3, 4, 5])
