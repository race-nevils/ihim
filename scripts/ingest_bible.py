#!/usr/bin/env python3
"""
Bible ingestion script — Phase G1 of workspace Second Brain.

Creates a 3-tier hierarchy in the knowledge graph:
  1 KJV Bible master entry
  66 book entries (isPartOf → master)
  1,189 chapter entries (isPartOf → book)

Uses low-level primitives (not store_new()) for batch efficiency.
Idempotent via source_filename dedup.

Usage:
    cd IHIM
    python -m scripts.ingest_bible --bible data/local/bible/raw [--dry-run] [--start-book Genesis]
"""

import argparse
import sys
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — resolve IHIM root from scripts/ directory
# ---------------------------------------------------------------------------
IHIM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(IHIM_ROOT))

from data.jsonld import create_brain_entry_jsonld, write_jsonld
from data.database import insert_entry, get_entry_by_source_filename, bulk_insert_relations
from handlers.utils import slugify, sanitize_title, compute_content_hash

logger = logging.getLogger(__name__)

WORKSPACE_ROOT = IHIM_ROOT.parent
OBSIDIAN_MEMORY = WORKSPACE_ROOT / "iHIM Vault" / "iHIM Memory"
CATEGORY = "Faith"
VERSION = "KJV"

# ---------------------------------------------------------------------------
# 66 Books of the Bible — canonical order
# (name, filename_stem, testament, order, chapter_count)
# ---------------------------------------------------------------------------
BOOK_CATALOG = [
    # -- Old Testament (39 books) --
    ("Genesis", "Genesis", "OT", 1, 50),
    ("Exodus", "Exodus", "OT", 2, 40),
    ("Leviticus", "Leviticus", "OT", 3, 27),
    ("Numbers", "Numbers", "OT", 4, 36),
    ("Deuteronomy", "Deuteronomy", "OT", 5, 34),
    ("Joshua", "Joshua", "OT", 6, 24),
    ("Judges", "Judges", "OT", 7, 21),
    ("Ruth", "Ruth", "OT", 8, 4),
    ("1 Samuel", "1Samuel", "OT", 9, 31),
    ("2 Samuel", "2Samuel", "OT", 10, 24),
    ("1 Kings", "1Kings", "OT", 11, 22),
    ("2 Kings", "2Kings", "OT", 12, 25),
    ("1 Chronicles", "1Chronicles", "OT", 13, 29),
    ("2 Chronicles", "2Chronicles", "OT", 14, 36),
    ("Ezra", "Ezra", "OT", 15, 10),
    ("Nehemiah", "Nehemiah", "OT", 16, 13),
    ("Esther", "Esther", "OT", 17, 10),
    ("Job", "Job", "OT", 18, 42),
    ("Psalms", "Psalms", "OT", 19, 150),
    ("Proverbs", "Proverbs", "OT", 20, 31),
    ("Ecclesiastes", "Ecclesiastes", "OT", 21, 12),
    ("Song of Solomon", "SongofSolomon", "OT", 22, 8),
    ("Isaiah", "Isaiah", "OT", 23, 66),
    ("Jeremiah", "Jeremiah", "OT", 24, 52),
    ("Lamentations", "Lamentations", "OT", 25, 5),
    ("Ezekiel", "Ezekiel", "OT", 26, 48),
    ("Daniel", "Daniel", "OT", 27, 12),
    ("Hosea", "Hosea", "OT", 28, 14),
    ("Joel", "Joel", "OT", 29, 3),
    ("Amos", "Amos", "OT", 30, 9),
    ("Obadiah", "Obadiah", "OT", 31, 1),
    ("Jonah", "Jonah", "OT", 32, 4),
    ("Micah", "Micah", "OT", 33, 7),
    ("Nahum", "Nahum", "OT", 34, 3),
    ("Habakkuk", "Habakkuk", "OT", 35, 3),
    ("Zephaniah", "Zephaniah", "OT", 36, 3),
    ("Haggai", "Haggai", "OT", 37, 2),
    ("Zechariah", "Zechariah", "OT", 38, 14),
    ("Malachi", "Malachi", "OT", 39, 4),
    # -- New Testament (27 books) --
    ("Matthew", "Matthew", "NT", 40, 28),
    ("Mark", "Mark", "NT", 41, 16),
    ("Luke", "Luke", "NT", 42, 24),
    ("John", "John", "NT", 43, 21),
    ("Acts", "Acts", "NT", 44, 28),
    ("Romans", "Romans", "NT", 45, 16),
    ("1 Corinthians", "1Corinthians", "NT", 46, 16),
    ("2 Corinthians", "2Corinthians", "NT", 47, 13),
    ("Galatians", "Galatians", "NT", 48, 6),
    ("Ephesians", "Ephesians", "NT", 49, 6),
    ("Philippians", "Philippians", "NT", 50, 4),
    ("Colossians", "Colossians", "NT", 51, 4),
    ("1 Thessalonians", "1Thessalonians", "NT", 52, 5),
    ("2 Thessalonians", "2Thessalonians", "NT", 53, 3),
    ("1 Timothy", "1Timothy", "NT", 54, 6),
    ("2 Timothy", "2Timothy", "NT", 55, 4),
    ("Titus", "Titus", "NT", 56, 3),
    ("Philemon", "Philemon", "NT", 57, 1),
    ("Hebrews", "Hebrews", "NT", 58, 13),
    ("James", "James", "NT", 59, 5),
    ("1 Peter", "1Peter", "NT", 60, 5),
    ("2 Peter", "2Peter", "NT", 61, 3),
    ("1 John", "1John", "NT", 62, 5),
    ("2 John", "2John", "NT", 63, 1),
    ("3 John", "3John", "NT", 64, 1),
    ("Jude", "Jude", "NT", 65, 1),
    ("Revelation", "Revelation", "NT", 66, 22),
]

# Brief descriptions for book-level entries
BOOK_DESCRIPTIONS = {
    "Genesis": "Creation, patriarchs, and the origin of Israel",
    "Exodus": "Israel's deliverance from Egypt and the giving of the Law",
    "Leviticus": "Laws of worship, sacrifice, and holiness",
    "Numbers": "Israel's wilderness wanderings and census records",
    "Deuteronomy": "Moses' final addresses and restatement of the Law",
    "Joshua": "Conquest and settlement of the Promised Land",
    "Judges": "Cycles of rebellion, oppression, and deliverance",
    "Ruth": "Loyalty, redemption, and the lineage of David",
    "1 Samuel": "Samuel, Saul, and David's rise to kingship",
    "2 Samuel": "David's reign over Israel",
    "1 Kings": "Solomon's glory and the divided kingdom",
    "2 Kings": "The decline and fall of Israel and Judah",
    "1 Chronicles": "David's reign from a priestly perspective",
    "2 Chronicles": "Solomon's temple and Judah's kings",
    "Ezra": "Return from exile and rebuilding the temple",
    "Nehemiah": "Rebuilding Jerusalem's walls and spiritual renewal",
    "Esther": "God's providence in preserving the Jewish people",
    "Job": "Suffering, faith, and God's sovereignty",
    "Psalms": "Prayers, praises, and songs of worship",
    "Proverbs": "Practical wisdom for daily living",
    "Ecclesiastes": "The search for meaning and life's purpose",
    "Song of Solomon": "Celebration of love and marriage",
    "Isaiah": "Messianic prophecy and God's judgment and comfort",
    "Jeremiah": "Warnings of judgment and promise of a new covenant",
    "Lamentations": "Grief over Jerusalem's destruction",
    "Ezekiel": "Visions of God's glory and Israel's restoration",
    "Daniel": "Faithfulness in exile and apocalyptic prophecy",
    "Hosea": "God's faithful love despite Israel's unfaithfulness",
    "Joel": "The Day of the Lord and the outpouring of the Spirit",
    "Amos": "Social justice and judgment on complacency",
    "Obadiah": "Judgment on Edom for pride against Israel",
    "Jonah": "God's mercy extends to all nations",
    "Micah": "Justice, mercy, and humble faithfulness",
    "Nahum": "Judgment on Nineveh for cruelty",
    "Habakkuk": "Wrestling with God over injustice and living by faith",
    "Zephaniah": "The Day of the Lord and restoration of the remnant",
    "Haggai": "Call to rebuild the temple after exile",
    "Zechariah": "Messianic visions and the coming kingdom",
    "Malachi": "Final prophetic call to covenant faithfulness",
    "Matthew": "Jesus as the promised Messiah and King of Israel",
    "Mark": "Jesus as the suffering Servant in action",
    "Luke": "Jesus as the Son of Man, savior of all people",
    "John": "Jesus as the divine Son of God and Word made flesh",
    "Acts": "The early church and the spread of the gospel",
    "Romans": "Justification by faith and the gospel explained",
    "1 Corinthians": "Church unity, spiritual gifts, and love",
    "2 Corinthians": "Paul's defense of his apostolic ministry",
    "Galatians": "Freedom in Christ from the law",
    "Ephesians": "The church as the body of Christ",
    "Philippians": "Joy and contentment in Christ",
    "Colossians": "The supremacy and sufficiency of Christ",
    "1 Thessalonians": "Encouragement and the return of Christ",
    "2 Thessalonians": "Clarification on the Day of the Lord",
    "1 Timothy": "Instructions for church leadership and sound doctrine",
    "2 Timothy": "Paul's final charge to endure in ministry",
    "Titus": "Godly living and church order on Crete",
    "Philemon": "Appeal for forgiveness and reconciliation",
    "Hebrews": "Christ's superiority and the new covenant",
    "James": "Faith demonstrated through works and practical wisdom",
    "1 Peter": "Hope and perseverance through suffering",
    "2 Peter": "Warnings against false teaching and the Second Coming",
    "1 John": "Assurance of salvation, love, and walking in the light",
    "2 John": "Guard truth and watch for deceivers",
    "3 John": "Commendation of hospitality and faithfulness",
    "Jude": "Contend for the faith against false teachers",
    "Revelation": "Apocalyptic vision of Christ's return and final victory",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_id_counter = 0

def _make_entry_id(slug: str) -> str:
    """Generate unique entry ID. Adds counter to avoid same-second collisions."""
    global _id_counter
    ts = datetime.now(timezone.utc)
    _id_counter += 1
    return f"brain-{ts.strftime('%Y%m%d%H%M%S')}-{_id_counter:04d}-{slug[:8]}"


def _make_timestamp() -> str:
    """ISO 8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _date_str() -> str:
    """YYYYMMDD for filenames."""
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _build_frontmatter(brain_id: str, jsonld_path: str, category: str,
                        created_at: str, content_hash: str) -> str:
    """YAML frontmatter for Obsidian files. Matches ingest.py pattern."""
    return (
        f"---\n"
        f"brain_id: {brain_id}\n"
        f"jsonld_path: {jsonld_path}\n"
        f"category: {category}\n"
        f"created_at: {created_at}\n"
        f"content_hash: {content_hash}\n"
        f"---\n"
    )


def format_chapter_text(verses: list[dict]) -> str:
    """Build chapter content with inline verse numbers."""
    lines = []
    for v in verses:
        lines.append(f"{v['verse']} {v['text']}")
    return "\n".join(lines)


def format_toc(catalog: list[tuple]) -> str:
    """Build master entry table of contents."""
    lines = ["# King James Version — Table of Contents\n"]
    lines.append("## Old Testament (39 books)\n")
    for name, _, testament, order, ch_count in catalog:
        if testament == "NT" and order == 40:
            lines.append("\n## New Testament (27 books)\n")
        lines.append(f"{order}. **{name}** — {ch_count} chapters")
    lines.append(f"\n---\n*66 books, 1,189 chapters*")
    return "\n".join(lines)


def load_bible(bible_dir: Path) -> dict:
    """
    Load per-book JSON files.
    Returns: {filename_stem: {"book": name, "chapters": [...]}}
    """
    data = {}
    for name, stem, *_ in BOOK_CATALOG:
        path = bible_dir / f"{stem}.json"
        if not path.exists():
            logger.error(f"Missing Bible file: {path}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            data[stem] = json.load(f)
    return data


def _write_obsidian(title: str, content: str, brain_id: str,
                     jsonld_path: str, created_at: str, content_hash: str,
                     subfolder: str = None) -> Path | None:
    """Write Obsidian markdown file. Non-fatal on failure."""
    try:
        if subfolder:
            obs_dir = OBSIDIAN_MEMORY / CATEGORY / subfolder
        else:
            obs_dir = OBSIDIAN_MEMORY / CATEGORY
        obs_dir.mkdir(parents=True, exist_ok=True)

        display_title = sanitize_title(title)
        obs_path = obs_dir / f"{display_title}.md"

        # Collision handling
        counter = 1
        while obs_path.exists():
            obs_path = obs_dir / f"{display_title} {counter}.md"
            counter += 1

        fm = _build_frontmatter(brain_id, jsonld_path, CATEGORY,
                                 created_at, content_hash)
        obs_path.write_text(fm + content, encoding="utf-8")
        return obs_path
    except Exception as e:
        logger.warning(f"Obsidian write failed for '{title}': {e}")
        return None


# ---------------------------------------------------------------------------
# Ingestion functions
# ---------------------------------------------------------------------------

def ingest_master(dry_run: bool = False) -> str | None:
    """Pass 1: Create the master KJV Bible entry. Returns entry_id."""
    source_filename = "bible-kjv-master"

    existing = get_entry_by_source_filename(source_filename)
    if existing:
        logger.info(f"SKIP (exists): KJV Bible master [{existing['id']}]")
        return existing["id"]

    title = "KJV Bible"
    content = format_toc(BOOK_CATALOG)
    summary = "King James Version — 66 books, 1,189 chapters, Old and New Testament"
    slug = slugify(title)
    content_hash = compute_content_hash(content)

    if dry_run:
        print(f"  [DRY-RUN] Would create: {title} (source_filename={source_filename})")
        return "dry-run-master"

    entry_id = _make_entry_id(slug)
    now = _make_timestamp()
    ds = _date_str()

    # JSON-LD
    jsonld_doc = create_brain_entry_jsonld(
        entry_id=entry_id, title=title, category=CATEGORY,
        content=content, summary=summary, confidence=1.0,
        source_file="bible-kjv", classifier="human",
        slug=slug, date_str=ds, source_section=None,
        ingest_method="bible-ingestion-g1", ingested_at=now,
    )
    # Inject Bible metadata
    jsonld_doc["ihim:version"] = VERSION
    jsonld_doc["ihim:entryType"] = "bible-master"

    jsonld_path = write_jsonld(jsonld_doc, CATEGORY, slug, ds)

    # SQLite
    insert_entry({
        "id": entry_id, "title": title, "category": CATEGORY,
        "content": content, "summary": summary, "confidence": 1.0,
        "source_file": "bible-kjv", "classifier": "human",
        "source_filename": source_filename,
        "content_hash": content_hash,
        "jsonld_path": str(jsonld_path),
        "first_seen_at": now,
    })

    # Obsidian — master goes at top-level Faith/
    _write_obsidian(title, content, entry_id, str(jsonld_path), now, content_hash)

    logger.info(f"CREATED: {title} [{entry_id}]")
    return entry_id


def ingest_book(name: str, stem: str, testament: str, order: int,
                chapter_count: int, master_id: str,
                dry_run: bool = False) -> str | None:
    """Pass 2: Create a book-level entry + isPartOf → master. Returns entry_id."""
    source_filename = f"bible-kjv-book-{slugify(name)}"

    existing = get_entry_by_source_filename(source_filename)
    if existing:
        logger.info(f"SKIP (exists): {name} [{existing['id']}]")
        return existing["id"]

    testament_full = "Old Testament" if testament == "OT" else "New Testament"
    desc = BOOK_DESCRIPTIONS.get(name, "")
    content = (
        f"# {name}\n\n"
        f"**Testament:** {testament_full}\n"
        f"**Book:** {order} of 66\n"
        f"**Chapters:** {chapter_count}\n"
        f"**Version:** King James Version (KJV)\n\n"
        f"{desc}\n"
    )
    summary = f"{name} — {testament_full}, Book {order}, {chapter_count} chapters (KJV)"
    slug = slugify(f"bible-kjv-{name}")
    content_hash = compute_content_hash(content)

    if dry_run:
        print(f"  [DRY-RUN] Would create: {name} (source_filename={source_filename})")
        return f"dry-run-book-{order}"

    entry_id = _make_entry_id(slug)
    now = _make_timestamp()
    ds = _date_str()

    # Build isPartOf relation for JSON-LD (ihim: prefixed keys for validation)
    relations = [{
        "ihim:target": master_id,
        "ihim:relationType": "isPartOf",
        "ihim:confidence": 1.0,
        "ihim:source": "manual",
    }]

    # JSON-LD
    jsonld_doc = create_brain_entry_jsonld(
        entry_id=entry_id, title=name, category=CATEGORY,
        content=content, summary=summary, confidence=1.0,
        source_file="bible-kjv", classifier="human",
        slug=slug, date_str=ds, source_section=None,
        ingest_method="bible-ingestion-g1", ingested_at=now,
        relations=relations,
    )
    # Inject Bible metadata
    jsonld_doc["ihim:version"] = VERSION
    jsonld_doc["ihim:testament"] = testament
    jsonld_doc["ihim:bookOrder"] = order
    jsonld_doc["ihim:chapterCount"] = chapter_count
    jsonld_doc["ihim:entryType"] = "bible-book"

    jsonld_path = write_jsonld(jsonld_doc, CATEGORY, slug, ds)

    # SQLite
    insert_entry({
        "id": entry_id, "title": name, "category": CATEGORY,
        "content": content, "summary": summary, "confidence": 1.0,
        "source_file": "bible-kjv", "classifier": "human",
        "source_filename": source_filename,
        "content_hash": content_hash,
        "jsonld_path": str(jsonld_path),
        "first_seen_at": now,
    })

    # isPartOf relation in SQLite
    bulk_insert_relations([{
        "source_id": entry_id,
        "target_id": master_id,
        "relation_type": "isPartOf",
        "confidence": 1.0,
        "extraction_source": "manual",
        "reasoning": f"{name} is a book in the KJV Bible",
    }])

    # Obsidian — book summary at Bible/{BookName}.md
    _write_obsidian(name, content, entry_id, str(jsonld_path), now, content_hash,
                     subfolder="Bible")

    logger.info(f"CREATED: {name} [{entry_id}]")
    return entry_id


def ingest_chapter(book_name: str, chapter_num: int, verses: list[dict],
                   testament: str, book_order: int, book_id: str,
                   dry_run: bool = False) -> str | None:
    """Pass 3: Create a chapter entry + isPartOf → book. Returns entry_id."""
    chapter_slug = slugify(book_name).rstrip("-")
    source_filename = f"bible-kjv-{chapter_slug}-{chapter_num}"
    title = f"{book_name} {chapter_num}"

    existing = get_entry_by_source_filename(source_filename)
    if existing:
        return existing["id"]  # silent skip for chapters (too many to log)

    content = format_chapter_text(verses)
    total_verses = len(verses)
    summary = f"{book_name} chapter {chapter_num} ({total_verses} verses, KJV)"
    slug = slugify(f"bible-kjv-{book_name}-{chapter_num}")
    content_hash = compute_content_hash(content)

    if dry_run:
        print(f"  [DRY-RUN] Would create: {title} (source_filename={source_filename})")
        return f"dry-run-ch-{chapter_slug}-{chapter_num}"

    entry_id = _make_entry_id(slug)
    now = _make_timestamp()
    ds = _date_str()

    # Build isPartOf relation for JSON-LD (ihim: prefixed keys for validation)
    relations = [{
        "ihim:target": book_id,
        "ihim:relationType": "isPartOf",
        "ihim:confidence": 1.0,
        "ihim:source": "manual",
    }]

    # JSON-LD
    jsonld_doc = create_brain_entry_jsonld(
        entry_id=entry_id, title=title, category=CATEGORY,
        content=content, summary=summary, confidence=1.0,
        source_file="bible-kjv", classifier="human",
        slug=slug, date_str=ds, source_section=None,
        ingest_method="bible-ingestion-g1", ingested_at=now,
        relations=relations,
    )
    # Inject Bible metadata
    jsonld_doc["ihim:version"] = VERSION
    jsonld_doc["ihim:testament"] = testament
    jsonld_doc["ihim:bookName"] = book_name
    jsonld_doc["ihim:bookOrder"] = book_order
    jsonld_doc["ihim:chapter"] = chapter_num
    jsonld_doc["ihim:totalVerses"] = total_verses
    jsonld_doc["ihim:entryType"] = "bible-chapter"

    jsonld_path = write_jsonld(jsonld_doc, CATEGORY, slug, ds)

    # SQLite
    insert_entry({
        "id": entry_id, "title": title, "category": CATEGORY,
        "content": content, "summary": summary, "confidence": 1.0,
        "source_file": "bible-kjv", "classifier": "human",
        "source_filename": source_filename,
        "content_hash": content_hash,
        "jsonld_path": str(jsonld_path),
        "first_seen_at": now,
    })

    # isPartOf relation in SQLite
    bulk_insert_relations([{
        "source_id": entry_id,
        "target_id": book_id,
        "relation_type": "isPartOf",
        "confidence": 1.0,
        "extraction_source": "manual",
        "reasoning": f"{title} is a chapter in {book_name}",
    }])

    # Obsidian — chapter at Bible/{BookName}/{Title}.md
    _write_obsidian(title, content, entry_id, str(jsonld_path), now, content_hash,
                     subfolder=f"Bible/{sanitize_title(book_name)}")

    return entry_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Ingest KJV Bible into iHIM knowledge graph (3-tier hierarchy)"
    )
    parser.add_argument("--bible", required=True,
                        help="Path to Bible JSON directory (per-book files)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing any files")
    parser.add_argument("--start-book", default=None,
                        help="Resume from this book (skip earlier books)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    bible_dir = Path(args.bible)
    if not bible_dir.is_dir():
        logger.error(f"Bible directory not found: {bible_dir}")
        sys.exit(1)

    # Load all Bible data
    logger.info("Loading Bible data...")
    bible_data = load_bible(bible_dir)
    if len(bible_data) != 66:
        logger.error(f"Expected 66 books, found {len(bible_data)}")
        sys.exit(1)
    logger.info(f"Loaded {len(bible_data)} books")

    start_time = time.time()
    created = 0
    skipped = 0
    errors = 0

    # Determine start point
    skip_until = args.start_book
    skipping = skip_until is not None

    # ---- Pass 1: Master entry ----
    logger.info("=" * 60)
    logger.info("PASS 1: Master Bible entry")
    logger.info("=" * 60)
    master_id = ingest_master(dry_run=args.dry_run)
    if master_id and not master_id.startswith("dry-run"):
        if master_id.startswith("brain-"):
            created += 1
        else:
            skipped += 1
    elif args.dry_run:
        created += 1

    # ---- Pass 2: Book entries ----
    logger.info("=" * 60)
    logger.info("PASS 2: 66 book entries")
    logger.info("=" * 60)
    book_ids = {}  # name → entry_id

    for name, stem, testament, order, ch_count in BOOK_CATALOG:
        if skipping:
            if name == skip_until:
                skipping = False
            else:
                logger.info(f"SKIP (--start-book): {name}")
                # Still need the ID for chapter relations
                existing = get_entry_by_source_filename(f"bible-kjv-book-{slugify(name)}")
                if existing:
                    book_ids[name] = existing["id"]
                continue

        book_id = ingest_book(name, stem, testament, order, ch_count,
                              master_id, dry_run=args.dry_run)
        if book_id:
            book_ids[name] = book_id
            created += 1
        else:
            logger.error(f"Failed to create book entry: {name}")
            errors += 1

    # ---- Pass 3: Chapter entries ----
    logger.info("=" * 60)
    logger.info("PASS 3: 1,189 chapter entries")
    logger.info("=" * 60)
    chapter_count = 0
    skipping = skip_until is not None

    for name, stem, testament, order, _ in BOOK_CATALOG:
        if skipping:
            if name == skip_until:
                skipping = False
            else:
                continue

        book_id = book_ids.get(name)
        if not book_id:
            logger.error(f"No book ID for {name} — skipping chapters")
            errors += 1
            continue

        book_data = bible_data.get(stem)
        if not book_data:
            logger.error(f"No data for {name} ({stem})")
            errors += 1
            continue

        for ch_data in book_data["chapters"]:
            ch_num = int(ch_data["chapter"])
            ch_id = ingest_chapter(
                book_name=name, chapter_num=ch_num,
                verses=ch_data["verses"],
                testament=testament, book_order=order,
                book_id=book_id, dry_run=args.dry_run,
            )
            if ch_id:
                created += 1
            else:
                errors += 1
            chapter_count += 1

            # Progress every 50 chapters
            if chapter_count % 50 == 0:
                elapsed = time.time() - start_time
                logger.info(f"  ... {chapter_count} chapters processed "
                            f"({elapsed:.1f}s elapsed)")

    # ---- Summary ----
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"COMPLETE in {elapsed:.1f}s")
    logger.info(f"  Created: {created}")
    logger.info(f"  Skipped: {skipped}")
    logger.info(f"  Errors:  {errors}")
    logger.info(f"  Total chapters processed: {chapter_count}")
    if args.dry_run:
        logger.info("  (DRY-RUN — no files written)")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
