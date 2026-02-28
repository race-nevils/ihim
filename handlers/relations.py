"""Knowledge Graph relation extraction for Second Brain.

ARCHITECTURE ROLE: Relation Discovery Engine
=============================================
Extracts relations between brain entries using a 4-layer pipeline:
    Layer 1: Exact title match (confidence 0.95)
    Layer 2: People first-name match (confidence 0.80)
    Layer 3: TF-IDF cosine similarity (threshold 0.6)
    Layer 4: LLM extraction (confidence from model) — see Session 3

Entity index is a lazy singleton, invalidated on data changes.
All extraction is non-fatal — if it fails, the entry still exists.

Design decisions from KNOWLEDGE-GRAPH.md (SEO-informed):
    Q4:  One relation per pair, most specific type wins
    Q15: LLM prompt includes title + category + content
    Q19: Selective re-extraction (preserve manual unless targeted)
    Q27: Corpus stopwords auto-generated (terms in >50% entries filtered)
"""

import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from data.jsonld import (
    RELATION_TYPES,
    RELATION_SOURCES,
    resolve_relation_conflict,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Content Tier System (SEO-informed relation targets)
# =============================================================================

# (max_words, target_min, target_max, use_llm)
CONTENT_TIERS = [
    (150,   1,  5,  False),  # Small
    (500,   2,  8,  True),   # Medium
    (1500,  5,  20, True),   # Large
    (999999, 10, 45, True),  # Huge
]


def _get_content_tier(word_count: int) -> tuple[int, int, bool]:
    """Return (target_min, target_max, use_llm) for a word count."""
    for max_words, tmin, tmax, llm in CONTENT_TIERS:
        if word_count <= max_words:
            return tmin, tmax, llm
    return 10, 45, True


# =============================================================================
# Common-word guards for first-name matching
# =============================================================================

# First names that are also common English words — require extra context
COMMON_WORD_NAMES = frozenset({
    "art", "bill", "bob", "brook", "bud", "chance", "chase", "clay",
    "cliff", "cole", "dale", "dawn", "dean", "drew", "duke", "earl",
    "faith", "fern", "ford", "gene", "grace", "grant", "guy", "heath",
    "hope", "hunter", "iris", "ivy", "jack", "jade", "joy", "lance",
    "lane", "lee", "lily", "mark", "matt", "may", "miles", "nick",
    "olive", "page", "pat", "pearl", "penny", "peter", "ray", "reed",
    "robin", "rose", "ruby", "sandy", "skip", "sterling", "sue",
    "summer", "ted", "terry", "victor", "violet", "wade", "will",
})


# =============================================================================
# Entity Index (lazy singleton)
# =============================================================================

class EntityIndex:
    """In-memory index of all brain entries for fast relation extraction.

    Lazy singleton pattern: builds on first access, invalidated on data changes.
    Q24: In-memory entity index with lazy rebuild.
    """

    _instance: Optional["EntityIndex"] = None
    _valid: bool = False

    def __init__(self):
        self._title_index: dict[str, str] = {}       # lowercase title -> entry_id
        self._first_name_index: dict[str, str] = {}   # lowercase first name -> entry_id
        self._entry_titles: dict[str, str] = {}        # entry_id -> original title
        self._entry_categories: dict[str, str] = {}    # entry_id -> category
        self._entry_contents: dict[str, str] = {}      # entry_id -> content
        self._tfidf_vectors: dict[str, dict[str, float]] = {}  # entry_id -> {term: weight}
        self._corpus_stopwords: set[str] = set()
        self._built = False

    @classmethod
    def get(cls) -> "EntityIndex":
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def invalidate(cls):
        """Mark the index as stale — will rebuild on next access."""
        if cls._instance is not None:
            cls._instance._built = False
            cls._valid = False
        logger.debug("Entity index invalidated")

    def ensure_built(self):
        """Build the index if not already built or if invalidated."""
        if not self._built:
            self.build()

    def build(self):
        """Load all entries and compute indexes.

        Reads from SQLite (the query index) since it's faster than
        iterating JSON-LD files on disk.
        """
        from data.database import get_all_entries

        entries = get_all_entries()
        logger.info(f"Building entity index from {len(entries)} entries")

        self._title_index.clear()
        self._first_name_index.clear()
        self._entry_titles.clear()
        self._entry_categories.clear()
        self._entry_contents.clear()
        self._tfidf_vectors.clear()
        self._corpus_stopwords.clear()

        # Phase 1: Build title and first-name indexes
        for entry in entries:
            eid = entry["id"]
            title = entry.get("title", "")
            category = entry.get("category", "Misc")
            content = entry.get("content", "")

            self._entry_titles[eid] = title
            self._entry_categories[eid] = category
            self._entry_contents[eid] = content

            # Title index: lowercase full title -> entry_id
            if title:
                lower_title = title.lower().strip()
                self._title_index[lower_title] = eid

            # First-name index: People category only
            if category == "People" and title:
                first_name = title.split()[0].lower().strip() if title.split() else ""
                if first_name and len(first_name) >= 2:
                    # Skip if it's a very common word (unless title is just the name)
                    if first_name not in COMMON_WORD_NAMES or len(title.split()) <= 2:
                        self._first_name_index[first_name] = eid

        # Phase 2: Compute TF-IDF vectors
        self._compute_tfidf(entries)

        self._built = True
        EntityIndex._valid = True
        logger.info(
            f"Entity index built: {len(self._title_index)} titles, "
            f"{len(self._first_name_index)} first names, "
            f"{len(self._tfidf_vectors)} TF-IDF vectors, "
            f"{len(self._corpus_stopwords)} corpus stopwords"
        )

    def _compute_tfidf(self, entries: list[dict]):
        """Compute TF-IDF vectors for all entries.

        Q27: Terms appearing in >50% of entries are corpus stopwords.
        """
        # Tokenize all documents
        doc_tokens: dict[str, list[str]] = {}
        doc_count = len(entries)
        if doc_count == 0:
            return

        # Document frequency counter
        df_counter: Counter = Counter()

        for entry in entries:
            eid = entry["id"]
            text = f"{entry.get('title', '')} {entry.get('content', '')}"
            tokens = _tokenize(text)
            doc_tokens[eid] = tokens

            # Count unique terms per document for DF
            unique_terms = set(tokens)
            for term in unique_terms:
                df_counter[term] += 1

        # Q27: Corpus stopwords — terms in >50% of entries
        threshold = doc_count * 0.5
        self._corpus_stopwords = {
            term for term, count in df_counter.items()
            if count > threshold
        }

        # Compute TF-IDF for each document
        for eid, tokens in doc_tokens.items():
            if not tokens:
                continue

            # Term frequency (normalized by doc length)
            tf_counter = Counter(tokens)
            doc_len = len(tokens)
            tfidf_vec = {}

            for term, tf in tf_counter.items():
                if term in self._corpus_stopwords:
                    continue
                df = df_counter.get(term, 1)
                # TF-IDF: (tf / doc_len) * log(N / df)
                idf = math.log(doc_count / df) if df > 0 else 0
                weight = (tf / doc_len) * idf
                if weight > 0:
                    tfidf_vec[term] = weight

            if tfidf_vec:
                self._tfidf_vectors[eid] = tfidf_vec


def invalidate_entity_index():
    """Public API to invalidate the entity index (called after data changes)."""
    EntityIndex.invalidate()


# =============================================================================
# Tokenization
# =============================================================================

_TOKEN_RE = re.compile(r'[a-z0-9]+')


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric terms."""
    return _TOKEN_RE.findall(text.lower())


# =============================================================================
# Layer 1: Exact Title Match
# =============================================================================

def get_title_matches(
    content: str,
    exclude_id: str,
) -> list[dict]:
    """Find entries whose full title appears in the content.

    Layer 1: Highest confidence (0.95). Fast string scan.

    Args:
        content: Text to scan for titles
        exclude_id: Entry ID to exclude (self)

    Returns:
        List of relation dicts
    """
    index = EntityIndex.get()
    index.ensure_built()

    content_lower = content.lower()
    matches = []

    for title_lower, target_id in index._title_index.items():
        if target_id == exclude_id:
            continue
        # Skip very short titles (< 3 chars) to avoid false positives
        if len(title_lower) < 3:
            continue
        if title_lower in content_lower:
            matches.append({
                "@type": "ihim:Relation",
                "ihim:target": f"ihim:brain/{target_id}",
                "ihim:relationType": "mentions",
                "ihim:confidence": 0.95,
                "ihim:source": "exact-match",
                "dateCreated": datetime.now(timezone.utc).isoformat(),
            })

    return matches


# =============================================================================
# Layer 2: First-Name People Match
# =============================================================================

def get_first_name_matches(
    content: str,
    exclude_id: str,
) -> list[dict]:
    """Find People entries whose first name appears in the content.

    Layer 2: Moderate confidence (0.80). Only for People category.
    Common-word guards prevent false positives (e.g., "Will" the verb).

    Args:
        content: Text to scan for first names
        exclude_id: Entry ID to exclude (self)

    Returns:
        List of relation dicts
    """
    index = EntityIndex.get()
    index.ensure_built()

    content_lower = content.lower()
    # Tokenize content for word-boundary matching
    content_words = set(_tokenize(content_lower))
    matches = []

    for first_name, target_id in index._first_name_index.items():
        if target_id == exclude_id:
            continue
        # Already caught by Layer 1 title match? Skip.
        full_title = index._entry_titles.get(target_id, "").lower()
        if full_title in content_lower:
            continue

        # Word-boundary match (not substring)
        if first_name in content_words:
            # Extra guard: common words require capitalized occurrence
            if first_name in COMMON_WORD_NAMES:
                # Check for capitalized version in original content
                capitalized = first_name.capitalize()
                if capitalized not in content:
                    continue

            matches.append({
                "@type": "ihim:Relation",
                "ihim:target": f"ihim:brain/{target_id}",
                "ihim:relationType": "mentions",
                "ihim:confidence": 0.80,
                "ihim:source": "first-name",
                "dateCreated": datetime.now(timezone.utc).isoformat(),
            })

    return matches


# =============================================================================
# Layer 3: TF-IDF Cosine Similarity
# =============================================================================

def get_tfidf_matches(
    entry_id: str,
    top_n: int = 10,
    threshold: float = 0.06,
) -> list[dict]:
    """Find entries with similar TF-IDF vectors via cosine similarity.

    Layer 3: Variable confidence (similarity score). Finds topical overlap.

    Args:
        entry_id: Source entry ID
        top_n: Maximum number of matches to return
        threshold: Minimum cosine similarity (0.06 works well for sparse vectors)

    Returns:
        List of relation dicts sorted by similarity descending
    """
    index = EntityIndex.get()
    index.ensure_built()

    source_vec = index._tfidf_vectors.get(entry_id)
    if not source_vec:
        return []

    similarities = []
    source_norm = _vec_norm(source_vec)
    if source_norm == 0:
        return []

    for target_id, target_vec in index._tfidf_vectors.items():
        if target_id == entry_id:
            continue

        # Cosine similarity (dot product / (norm_a * norm_b))
        dot = sum(source_vec.get(t, 0) * target_vec.get(t, 0)
                  for t in source_vec if t in target_vec)
        if dot == 0:
            continue

        target_norm = _vec_norm(target_vec)
        if target_norm == 0:
            continue

        sim = dot / (source_norm * target_norm)
        if sim >= threshold:
            similarities.append((target_id, sim))

    # Sort by similarity descending, take top_n
    similarities.sort(key=lambda x: x[1], reverse=True)
    matches = []

    for target_id, sim in similarities[:top_n]:
        # Map similarity to confidence: 0.06-1.0 -> 0.50-0.90
        confidence = min(0.50 + (sim * 0.40 / 0.5), 0.90)
        matches.append({
            "@type": "ihim:Relation",
            "ihim:target": f"ihim:brain/{target_id}",
            "ihim:relationType": "relatedTo",
            "ihim:confidence": round(confidence, 3),
            "ihim:source": "tfidf",
            "dateCreated": datetime.now(timezone.utc).isoformat(),
        })

    return matches


def _vec_norm(vec: dict[str, float]) -> float:
    """Compute L2 norm of a sparse vector."""
    return math.sqrt(sum(v * v for v in vec.values()))


# =============================================================================
# Main Extraction Function
# =============================================================================

def extract_relations(
    entry_id: str,
    title: str,
    category: str,
    content: str,
    use_llm: bool = True,
) -> list[dict]:
    """Extract relations for a single entry using the 4-layer pipeline.

    Runs layers sequentially, deduplicates per Q4 (one relation per pair,
    most specific type wins), caps to tier max.

    Args:
        entry_id: Source entry ID
        title: Entry title
        category: Entry category
        content: Entry text content
        use_llm: Whether to attempt LLM extraction (Layer 4)

    Returns:
        List of deduplicated relation dicts, capped to tier max
    """
    word_count = len(content.split()) if content else 0
    tier_min, tier_max, tier_llm = _get_content_tier(word_count)

    # Collect all relations from deterministic layers
    all_relations: list[dict] = []

    # Layer 1: Exact title matches
    try:
        title_matches = get_title_matches(content, entry_id)
        all_relations.extend(title_matches)
    except Exception as e:
        logger.warning(f"Layer 1 (title match) failed for {entry_id}: {e}")

    # Layer 2: First-name People matches
    try:
        name_matches = get_first_name_matches(content, entry_id)
        all_relations.extend(name_matches)
    except Exception as e:
        logger.warning(f"Layer 2 (first-name) failed for {entry_id}: {e}")

    # Layer 3: TF-IDF similarity
    try:
        tfidf_matches = get_tfidf_matches(entry_id)
        all_relations.extend(tfidf_matches)
    except Exception as e:
        logger.warning(f"Layer 3 (TF-IDF) failed for {entry_id}: {e}")

    # Layer 4: LLM extraction
    if use_llm and tier_llm and len(all_relations) < tier_min:
        try:
            llm_matches = _extract_llm(
                entry_id, title, category, content,
                word_count, all_relations,
            )
            all_relations.extend(llm_matches)
        except Exception as e:
            logger.warning(f"Layer 4 (LLM) failed for {entry_id}: {e}")

    # Deduplicate: Q4 — one relation per source→target pair
    deduped = _deduplicate_relations(all_relations)

    # Cap to tier max
    if len(deduped) > tier_max:
        # Sort by confidence descending, keep top tier_max
        deduped.sort(key=lambda r: r.get("ihim:confidence", 0), reverse=True)
        deduped = deduped[:tier_max]

    return deduped


def _deduplicate_relations(relations: list[dict]) -> list[dict]:
    """Deduplicate relations by target entry ID.

    Q4: One relation per source→target pair. Most specific type wins,
    higher confidence taken.

    Args:
        relations: List of relation dicts (may have duplicates)

    Returns:
        Deduplicated list
    """
    seen: dict[str, dict] = {}  # target_id -> best relation

    for rel in relations:
        target = rel.get("ihim:target", "")
        if target in seen:
            seen[target] = resolve_relation_conflict(seen[target], rel)
        else:
            seen[target] = dict(rel)

    return list(seen.values())


# =============================================================================
# Layer 4: LLM Extraction (Session 3 — B2b)
# =============================================================================

_LLM_CHUNK_SIZE = 1200  # words per chunk (with overlap)
_LLM_CHUNK_OVERLAP = 100  # words overlap between chunks


def _chunk_content(content: str, word_count: int) -> list[str]:
    """Split large content into section-aware chunks for LLM processing.

    Tries to split at H2/H3 headers first, falls back to word-based chunking.

    Args:
        content: Full entry text
        word_count: Pre-computed word count

    Returns:
        List of content chunks
    """
    if word_count <= _LLM_CHUNK_SIZE:
        return [content]

    # Try section-aware splitting at ## or ### headers
    sections = re.split(r'\n(?=#{2,3}\s)', content)
    if len(sections) > 1:
        chunks = []
        current_chunk = ""
        for section in sections:
            section_words = len(section.split())
            if len(current_chunk.split()) + section_words > _LLM_CHUNK_SIZE and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = section
            else:
                current_chunk += "\n" + section if current_chunk else section
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        return chunks if chunks else [content]

    # Fallback: word-based chunking with overlap
    words = content.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + _LLM_CHUNK_SIZE, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start = end - _LLM_CHUNK_OVERLAP
        if start >= len(words) - _LLM_CHUNK_OVERLAP:
            break

    return chunks if chunks else [content]


def _get_llm_candidates(
    entry_id: str,
    existing_targets: set[str],
    max_candidates: int = 30,
) -> list[dict]:
    """Select candidate entries for LLM evaluation.

    Picks entries the deterministic layers missed — same category first,
    then cross-category entries with high TF-IDF overlap.

    Args:
        entry_id: Source entry ID
        existing_targets: Set of target IDs already found by Layers 1-3
        max_candidates: Maximum candidates to present to LLM

    Returns:
        List of candidate dicts with id, title, category
    """
    index = EntityIndex.get()
    index.ensure_built()

    candidates = []
    source_category = index._entry_categories.get(entry_id, "")

    # Priority 1: Same category entries not yet linked
    for eid, cat in index._entry_categories.items():
        if eid == entry_id or eid in existing_targets:
            continue
        if cat == source_category:
            candidates.append({
                "id": eid,
                "title": index._entry_titles.get(eid, ""),
                "category": cat,
            })

    # Priority 2: Cross-category entries with some TF-IDF overlap
    source_vec = index._tfidf_vectors.get(entry_id, {})
    if source_vec:
        cross_category = []
        source_terms = set(source_vec.keys())
        for eid, vec in index._tfidf_vectors.items():
            if eid == entry_id or eid in existing_targets:
                continue
            if index._entry_categories.get(eid) == source_category:
                continue  # Already in priority 1
            overlap = len(source_terms & set(vec.keys()))
            if overlap > 0:
                cross_category.append((eid, overlap))

        cross_category.sort(key=lambda x: x[1], reverse=True)
        for eid, _ in cross_category:
            candidates.append({
                "id": eid,
                "title": index._entry_titles.get(eid, ""),
                "category": index._entry_categories.get(eid, ""),
            })

    return candidates[:max_candidates]


def _extract_llm_single_chunk(
    entry_id: str,
    title: str,
    category: str,
    chunk: str,
    candidates: list[dict],
) -> list[dict]:
    """Run one LLM call to extract relations from a content chunk.

    Args:
        entry_id: Source entry ID
        title: Source entry title
        category: Source entry category
        chunk: Content chunk to analyze
        candidates: List of candidate entries to consider

    Returns:
        List of validated relation dicts
    """
    if not candidates:
        return []

    # Build candidate list for the prompt
    candidate_lines = "\n".join(
        f"- ID: {c['id']} | Title: {c['title']} | Category: {c['category']}"
        for c in candidates
    )

    prompt = f"""You are analyzing a knowledge base entry to find connections to other entries.

SOURCE ENTRY:
- Title: {title}
- Category: {category}
- Content: {chunk[:2000]}

CANDIDATE ENTRIES (these are the ONLY valid targets):
{candidate_lines}

RELATION TYPES (ordered by specificity):
- derivedFrom: This entry evolved from or was inspired by the target
- supersedes: This entry replaces or updates the target
- isPartOf: This entry is a subtask or subcomponent of the target
- hasPart: The target is a subtask or subcomponent of this entry
- citation: This entry cites or references the target
- mentions: The target entity is mentioned by name in this entry
- relatedTo: Topical or contextual connection between entries

RULES:
1. Only return relations to candidates from the list above
2. Use the most specific relation type that applies
3. Rate confidence 0.5-0.95 (higher = more certain)
4. Return at most 10 relations
5. Only include relations you're genuinely confident about

Return a JSON array of objects. Each object must have:
- "target_id": exact ID from the candidate list
- "relation_type": one of the types listed above
- "confidence": float between 0.5 and 0.95
- "reasoning": brief explanation (1 sentence)

Return ONLY the JSON array, no other text. If no relations found, return [].
"""

    try:
        from adapters.ollama import OllamaAdapter
        adapter = OllamaAdapter()
        response = adapter.generate(
            prompt=prompt,
            model=OllamaAdapter.FAST_MODEL,
            format="json",
        )

        if not response:
            return []

        # Parse JSON response
        import json
        # Handle wrapped JSON (sometimes models add markdown fencing)
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)

        parsed = json.loads(text)
        if not isinstance(parsed, list):
            # Some models wrap in an object
            if isinstance(parsed, dict) and "relations" in parsed:
                parsed = parsed["relations"]
            else:
                return []

        # Validate: only accept targets from our candidate list
        valid_ids = {c["id"] for c in candidates}
        valid_types = set(RELATION_TYPES)
        now = datetime.now(timezone.utc).isoformat()
        validated = []

        for item in parsed:
            if not isinstance(item, dict):
                continue
            target_id = item.get("target_id", "")
            rel_type = item.get("relation_type", "")
            confidence = item.get("confidence", 0.5)
            reasoning = item.get("reasoning", "")

            # Hallucination guard: target must be in candidate list
            if target_id not in valid_ids:
                logger.debug(f"LLM hallucinated target_id: {target_id}")
                continue
            if rel_type not in valid_types:
                rel_type = "relatedTo"  # Fallback to generic

            # Clamp confidence
            confidence = max(0.5, min(0.95, float(confidence)))

            validated.append({
                "@type": "ihim:Relation",
                "ihim:target": f"ihim:brain/{target_id}",
                "ihim:relationType": rel_type,
                "ihim:confidence": round(confidence, 3),
                "ihim:source": "llm",
                "ihim:reasoning": reasoning[:200] if reasoning else None,
                "dateCreated": now,
            })

        return validated

    except Exception as e:
        logger.warning(f"LLM extraction failed for chunk of {entry_id}: {e}")
        return []


def _extract_llm(
    entry_id: str,
    title: str,
    category: str,
    content: str,
    word_count: int,
    existing_relations: list[dict],
) -> list[dict]:
    """Orchestrate chunked LLM extraction.

    Only runs when deterministic layers found < target minimum.
    Graceful degradation: if Ollama unreachable, returns empty.

    Args:
        entry_id: Source entry ID
        title: Entry title
        category: Entry category
        content: Full entry content
        word_count: Pre-computed word count
        existing_relations: Relations already found by Layers 1-3

    Returns:
        List of new relation dicts from LLM
    """
    # Health check: skip if Ollama unreachable
    try:
        from adapters.embeddings import EmbeddingAdapter
        with EmbeddingAdapter() as adapter:
            if not adapter.health_check():
                logger.info("Skipping LLM extraction: Ollama not reachable")
                return []
    except Exception:
        logger.info("Skipping LLM extraction: health check failed")
        return []

    # Get existing target IDs to avoid re-evaluating
    existing_targets = set()
    for rel in existing_relations:
        target = rel.get("ihim:target", "")
        # Extract entry_id from "ihim:brain/{entry_id}"
        if target.startswith("ihim:brain/"):
            existing_targets.add(target[len("ihim:brain/"):])

    # Get candidates
    candidates = _get_llm_candidates(entry_id, existing_targets)
    if not candidates:
        return []

    # Chunk content
    chunks = _chunk_content(content, word_count)

    # Process each chunk
    all_llm_relations = []
    for chunk in chunks:
        chunk_relations = _extract_llm_single_chunk(
            entry_id, title, category, chunk, candidates,
        )
        all_llm_relations.extend(chunk_relations)

    return all_llm_relations


def extract_relations_orphan_pass(
    entry_id: str,
    title: str,
    category: str,
    content: str,
) -> list[dict]:
    """Broader LLM pass for zero-relation entries (orphan remediation).

    Uses a wider candidate set and lower thresholds to find at least
    one connection for orphaned entries.

    Args:
        entry_id: Source entry ID
        title: Entry title
        category: Entry category
        content: Entry content

    Returns:
        List of relation dicts
    """
    index = EntityIndex.get()
    index.ensure_built()

    # Build wider candidate set: all entries except self
    candidates = []
    for eid, t in index._entry_titles.items():
        if eid == entry_id:
            continue
        candidates.append({
            "id": eid,
            "title": t,
            "category": index._entry_categories.get(eid, ""),
        })

    # Limit to 50 candidates (prioritize same category)
    same_cat = [c for c in candidates if c["category"] == category]
    other_cat = [c for c in candidates if c["category"] != category]
    candidates = (same_cat + other_cat)[:50]

    if not candidates:
        return []

    word_count = len(content.split()) if content else 0
    chunks = _chunk_content(content, word_count)

    all_relations = []
    for chunk in chunks[:2]:  # Limit to 2 chunks for orphan pass
        chunk_relations = _extract_llm_single_chunk(
            entry_id, title, category, chunk, candidates,
        )
        all_relations.extend(chunk_relations)

    return _deduplicate_relations(all_relations)


# =============================================================================
# Retroactive Bootstrap (Session 8 — B8)
# =============================================================================

def bootstrap_relations(
    dry_run: bool = False,
    batch_size: int = 50,
    use_llm: bool = False,
    progress_callback=None,
) -> dict:
    """Process all entries through the 4-layer extraction pipeline.

    The "big bang" — runs extraction over all entries, handles backlinks,
    runs orphan remediation. Can be run incrementally (skips entries that
    already have relations unless force=True).

    Args:
        dry_run: If True, report what would happen without making changes
        batch_size: Number of entries to process per batch
        use_llm: Whether to enable Layer 4 (LLM extraction)
        progress_callback: Optional callback(current, total, entry_id)

    Returns:
        Detailed report dict
    """
    from data.database import (
        get_all_entries, get_connection, bulk_insert_relations,
        get_orphan_entries, delete_relations_for_entry,
    )
    from data.jsonld import read_jsonld, update_jsonld

    logger.info(f"Bootstrap started: dry_run={dry_run}, use_llm={use_llm}")

    # Build entity index first
    index = EntityIndex.get()
    index.build()

    entries = get_all_entries()
    total = len(entries)

    report = {
        "dry_run": dry_run,
        "total_entries": total,
        "processed": 0,
        "relations_created": 0,
        "backlinks_created": 0,
        "errors": [],
        "entries_with_relations": 0,
        "orphans_before": 0,
        "orphans_after": 0,
        "by_source": {},
    }

    # Count orphans before
    orphans_before = get_orphan_entries()
    report["orphans_before"] = len(orphans_before)

    # Process in batches
    for i in range(0, total, batch_size):
        batch = entries[i:i + batch_size]

        for entry in batch:
            entry_id = entry["id"]
            title = entry.get("title", "")
            category = entry.get("category", "Misc")
            content = entry.get("content", "")

            if progress_callback:
                progress_callback(report["processed"], total, entry_id)

            try:
                # Extract relations
                relations = extract_relations(
                    entry_id, title, category, content,
                    use_llm=use_llm,
                )

                if not relations:
                    report["processed"] += 1
                    continue

                if dry_run:
                    report["relations_created"] += len(relations)
                    report["entries_with_relations"] += 1
                    report["processed"] += 1
                    # Track by source
                    for rel in relations:
                        src = rel.get("ihim:source", "unknown")
                        report["by_source"][src] = report["by_source"].get(src, 0) + 1
                    continue

                # Store relations in SQLite
                db_relations = []
                for rel in relations:
                    target = rel.get("ihim:target", "")
                    target_id = (
                        target.replace("ihim:brain/", "")
                        if target.startswith("ihim:brain/") else target
                    )
                    db_relations.append({
                        "source_id": entry_id,
                        "target_id": target_id,
                        "relation_type": rel.get("ihim:relationType", "relatedTo"),
                        "confidence": rel.get("ihim:confidence", 0.5),
                        "extraction_source": rel.get("ihim:source", "unknown"),
                        "reasoning": rel.get("ihim:reasoning"),
                    })

                    # Track by source
                    src = rel.get("ihim:source", "unknown")
                    report["by_source"][src] = report["by_source"].get(src, 0) + 1

                inserted = bulk_insert_relations(db_relations)
                report["relations_created"] += inserted

                # Update JSON-LD source of truth
                jsonld_path = entry.get("jsonld_path")
                if jsonld_path:
                    from pathlib import Path as _Path
                    p = _Path(jsonld_path)
                    if p.exists():
                        try:
                            update_jsonld(p, {"ihim:relations": relations})
                        except Exception as e:
                            logger.debug(f"JSON-LD update failed for {entry_id}: {e}")

                if inserted > 0:
                    report["entries_with_relations"] += 1

                # Write backlinks
                try:
                    from handlers.storage import _write_backlinks
                    _write_backlinks(entry_id, title, relations)
                except Exception as e:
                    logger.debug(f"Backlink write failed for {entry_id}: {e}")

            except Exception as e:
                report["errors"].append({
                    "entry_id": entry_id,
                    "error": str(e),
                })
                logger.warning(f"Bootstrap failed for {entry_id}: {e}")

            report["processed"] += 1

    # Orphan remediation pass (if LLM enabled)
    if use_llm and not dry_run:
        orphans = get_orphan_entries()
        logger.info(f"Orphan remediation: {len(orphans)} orphans found")

        for orphan in orphans:
            try:
                entry_id = orphan["id"]
                # Look up full entry
                entry = next((e for e in entries if e["id"] == entry_id), None)
                if not entry:
                    continue

                relations = extract_relations_orphan_pass(
                    entry_id,
                    entry.get("title", ""),
                    entry.get("category", "Misc"),
                    entry.get("content", ""),
                )

                if relations:
                    db_relations = []
                    for rel in relations:
                        target = rel.get("ihim:target", "")
                        target_id = (
                            target.replace("ihim:brain/", "")
                            if target.startswith("ihim:brain/") else target
                        )
                        db_relations.append({
                            "source_id": entry_id,
                            "target_id": target_id,
                            "relation_type": rel.get("ihim:relationType", "relatedTo"),
                            "confidence": rel.get("ihim:confidence", 0.5),
                            "extraction_source": rel.get("ihim:source", "unknown"),
                            "reasoning": rel.get("ihim:reasoning"),
                        })

                    inserted = bulk_insert_relations(db_relations)
                    report["relations_created"] += inserted

            except Exception as e:
                report["errors"].append({
                    "entry_id": orphan["id"],
                    "error": f"orphan_pass: {e}",
                })

    # Final orphan count
    if not dry_run:
        orphans_after = get_orphan_entries()
        report["orphans_after"] = len(orphans_after)
    else:
        report["orphans_after"] = report["orphans_before"]

    report["error_count"] = len(report["errors"])

    logger.info(
        f"Bootstrap complete: {report['processed']}/{total} entries, "
        f"{report['relations_created']} relations, "
        f"{report['error_count']} errors"
    )

    return report
