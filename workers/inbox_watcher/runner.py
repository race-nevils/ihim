"""Entry point for the inbox watcher worker."""
import sys
from pathlib import Path

# Add IHIM to path for imports
IHIM_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(IHIM_ROOT))

from orchestrator.graph import create_orchestrator
from workers.inbox_watcher.watcher import InboxWatcher, InboxSource


# Paths
WORKSPACE_ROOT = IHIM_ROOT.parent
PROCESSED_PATH = IHIM_ROOT / "data" / "local" / "brain" / "processed"

# Inbox sources - desktop and mobile
DESKTOP_INBOX = InboxSource(
    path=IHIM_ROOT / "data" / "local" / "brain" / "inbox",
    cleanup="move"  # Archive to processed folder
)

OBSIDIAN_INBOX = InboxSource(
    path=WORKSPACE_ROOT / "Obsidian Vault" / "iHIM",
    cleanup="move",  # Also archive (move deletes original)
    exclude_folders={".obsidian", "iHIM Memory", "processed"}
)


def create_processor(orchestrator):
    """Create a processor function that uses the orchestrator.

    Args:
        orchestrator: Compiled LangGraph orchestrator

    Returns:
        Processor function compatible with InboxWatcher
    """
    def processor(content: str, source_file: str) -> dict:
        result = orchestrator.invoke({
            "input_text": content,
            "source_file": source_file
        })
        return result

    return processor


def main():
    """Main entry point for the inbox watcher."""
    print("=" * 60)
    print("Second Brain Orchestrator - Inbox Watcher")
    print("=" * 60)
    print()

    # Create orchestrator
    print("Initializing orchestrator...")
    orchestrator = create_orchestrator()
    print("Orchestrator ready.\n")

    # Create watcher with both sources
    watcher = InboxWatcher(
        sources=[DESKTOP_INBOX, OBSIDIAN_INBOX],
        processed_path=PROCESSED_PATH,
        poll_interval=2.0,
        cleanup_days=7  # Auto-delete processed files older than 7 days
    )

    # Create processor
    processor = create_processor(orchestrator)

    # Start watching
    watcher.watch(processor)


if __name__ == "__main__":
    main()
