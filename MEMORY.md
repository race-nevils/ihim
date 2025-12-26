# iHIM Memory
Updated: 2025-12-25

## Project
**iHIM** - EdgeFlow AI Command Center
Personal cockpit for company workflows. One-click actions. Local-first, modular, untethered.

## Principles
- FREE (no mandatory costs)
- LOCAL (runs on your machines)
- MODULAR (swap any component)
- UNTETHERED (no API dependencies)
- SELF-HEALING (recovers from failures)

## Status
Phase 1: Foundation (Building)

## Stack
- **Brain:** Ollama + Qwen 2.5 3B (local, ~8GB RAM constraint)
- **Backend:** Python + FastAPI
- **Database:** SQLite (portable, zero-config)
- **Search:** ChromaDB (local vector search)
- **UI:** Web dashboard (served by Python)
- **Host:** Windows Desktop

## Structure
```
iHIM/
├── core/           # Core interfaces (LLM, storage, search)
├── actions/        # One-click workflow actions
├── api/            # FastAPI backend
├── ui/             # Web dashboard
├── data/           # SQLite + ChromaDB
└── run.py          # Start everything
```

## Key Concept
Local LLM is the DISPATCHER, not the only brain.
- Simple tasks → handled locally
- Complex tasks → queued for the agent harness escalation
- /commands route to specific actions

## Recent
- Cross-platform venv setup: `.venv/` excluded from Syncthing, each OS has own
- Updated `run.py` to auto-detect and use venv (Mac/Windows)
- Created `.stignore` to exclude `.venv`, `__pycache__`, `.pyc`, `.DS_Store`
- Ollama installed, Qwen 2.5 3B working
- Architecture decided: Python + FastAPI + SQLite + ChromaDB

---
Archive: (append sessions below when needed)
