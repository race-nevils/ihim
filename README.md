# iHIM — the operator's Command Center

Local-first personal dashboard: Whisper dictation, meeting recorder, health program, and the JSON-LD second-brain data layer. FastAPI backend; the frontend is native Web Components end-to-end (every widget is a custom element — windows subclass `IhimPanel`), everything served from one process on `127.0.0.1:7777`.

Rebuilt from scratch 2026-06-10 (design + audit: `design-notes/ihim/refactor-2026-06/`). Pre-refactor code archived at `archive/ihim-pre-refactor-20260609/`.

## Run

```powershell
# canonical (idempotent — no-op if already healthy)
powershell -File scripts\server.ps1 start            # port 7777
powershell -File scripts\server.ps1 restart -Port 7778   # test instance
powershell -File scripts\server.ps1 status|stop

# direct
python run.py [--port 7777] [--dev]    # --dev = auto-reload (development only)
```

- **No reloader in normal operation** — one process, one PID. `--dev` opts in.
- Test instances: set `IHIM_STT_AUTOSTART=0` so they never grab the global dictation hotkey or GPU.
- Login autostart: `ihim-master.ahk` (shell:startup) → `server.ps1 start`.
- Server console: `data/server-console.log` · lifecycle log: `data/server-lifecycle.log`.

## Layout

```
run.py / run_silent.py     entry + silent shim (startup .vbs contract)
scripts/server.ps1         the ONLY start/stop/restart/status tool
api/
  main.py                  app factory — explicit router registration
  runtime.py middleware.py errors.py responses.py site.py server.py
  stt/ recorder/         dictation + meeting recorder (shared whisper core)
  health/ brain/ graph/ preferences.py todos.py
tools/stt/               dictation engine (hotkey→capture→transcribe→inject)
                           data/ = dictation history + voice-training audio
handlers/ adapters/ data/  brain ingestion pipeline + JSON-LD source of truth
                           (data/local/brain/ = SSOT; data/brain.db = index)
orchestrator/              pipeline state (PipelineState/OrchestratorState — handlers/brain.py)
ui/                        index.html + static/js (components/ = all widgets) + style.css
tests/                     pytest
```

## Widgets

STT (speech-to-text dictation — history/copy/correct/vocab, SSE status; engine subsystem stays `stt` in paths/APIs) · Meeting Recorder (taskbar chip shows a red outline while recording) · Health · To-Do (quick-capture list grouped by category — `data/local/todos.json`) · YT Transcriber · CPU/RAM bar · Taskbar (Windows-style bottom-bar chip per open window — click to minimize/restore, drag to reorder, state persists across reloads) · top-right ⋮ options menu (screen-level actions: Restart Server). *Stopwatch deleted 2026-07-27.*

*Vault deleted 2026-07-17: widget, `api/vault/`, and the task_status query layer — replaced by the To-Do widget. Brain entries remain queryable via `api/brain/`.*

*Google Calendar deleted 2026-07-17: widget, `api/calendar/`, brain auto-push, and the rebuild GCal executor. Brain-internal event detection (notes → `event_date` in brain.db) remains.*

*agent node deleted 2026-07-17: bar chip, window, and `api/agentnode/` proxy. The agent node itself and its blueprint (`agent-node-blueprint/`) are untouched — this removed only the in-app control surface.*

## Architecture notes

- **Zero WebSockets.** STT status = SSE (`/api/stt/status/stream`); everything else polls. Nothing to leak or drop.
- Errors are RFC 9457 `application/problem+json`; success uses `{"success": true}` envelopes.
- CSP/security headers on every response (report-only CSP while UI stabilizes).
- Frontend cache busting: per-boot `BOOT_ID` importmap + 3s `/api/boot-id` polling → edits to ui/ hot-reload the page without a server restart.
- Brain data contracts (Unison sync, /rebuild) documented in `harness/rules/ihim.md`.

## Test gates

```powershell
cd IHIM && python -m pytest                          # route + guard tests
```
