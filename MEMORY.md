# iHIM Memory
Updated: 2026-01-25

## Project
**iHIM** - Personal ARLM Implementation
the operator's command center for personal workflows. Local-first, sovereign, auditable.

## Principles
- **FREE** (no mandatory costs)
- **LOCAL** (runs on your machines)
- **SOVEREIGN** (you control all data)
- **AUDITABLE** (everything traceable via JSON-LD + C2PA)
- **REPRODUCIBLE** (anyone can rebuild from source of truth)

## Status
Phase 2: JSON-LD Foundation (Building)

## Stack
- **Data (Source of Truth):** JSON-LD files in `data/local/brain/`
- **Index:** SQLite (query layer, derived from JSON-LD)
- **Human View:** Obsidian Markdown (derived from JSON-LD)
- **Brain:** Ollama + Qwen 2.5 (local LLM)
- **Backend:** Python + FastAPI
- **UI:** Web dashboard (served by FastAPI)
- **Host:** Windows Desktop

## Data Architecture

```
Raw Capture (mobile/desktop)
       ↓
   Orchestrator (classify → store)
       ↓
   JSON-LD File (source of truth)
       ├── SQLite index (fast queries)
       └── Markdown (Obsidian view)
```

**Paths:**
| Layer | Path |
|-------|------|
| JSON-LD | `IHIM/data/local/brain/{slug}-{date}.jsonld` |
| SQLite | `IHIM/data/brain.db` |
| Obsidian | `Obsidian Vault/iHIM/iHIM Memory/{Category}/` |

**Vocabulary:** Schema.org (base) + Dublin Core + ActivityStreams + ihim: (custom)

**Integrity:** SHA-256 hash of JSON-LD stored in database for provenance chain.

## Structure
```
IHIM/
├── orchestrator/     # Intent detection, state, routing
├── handlers/         # brain, chat, calendar, task
├── workers/          # inbox_watcher (file monitoring)
├── adapters/         # Ollama LLM adapter
├── api/              # FastAPI backend + C2PA routes
├── data/             # SQLite, JSON-LD, standards library
├── ui/               # Web dashboard
└── run.py            # Start server
```

## Key Concept
JSON-LD is the atomic building block. Everything else derives from it.
- JSON-LD = source of truth (semantic, portable, signable)
- Database = query index (fast, rebuildable)
- Markdown = human view (readable, browsable)

## Recent
- JSON-LD architecture locked in as single source of truth
- Database role clarified: index over JSON-LD, not parallel store
- Staging registry to be eliminated (database handles file tracking)
- Vocabulary aligned: Schema.org + DC + AS + ihim:
- File naming: {slug}-{date}.jsonld

---
Archive: (append sessions below when needed)
