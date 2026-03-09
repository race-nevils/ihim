"""Base class for structured content adapters.

Adapters decompose structured files (JSON, etc.) into individual brain entries.
Each adapter knows how to parse a specific file format and yield entry dicts
that feed directly into ingest().
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator


class ContentAdapter(ABC):
    """Interface for structured file → brain entry decomposition."""

    @abstractmethod
    def can_handle(self, file_path: Path) -> bool:
        """Check if this adapter handles the given file.

        Match by filename (not just extension) — .json is too broad.
        """
        ...

    @abstractmethod
    def extract_entries(self, file_path: Path) -> Iterator[dict]:
        """Yield entry dicts from a structured file.

        Each dict must contain:
            title: str        — entry title (include source_id for dedup)
            category: str     — brain category
            summary: str      — one-line summary
            content: str      — formatted content (markdown)
            source_id: str    — unique ID within the file (used as section for dedup)
        """
        ...
