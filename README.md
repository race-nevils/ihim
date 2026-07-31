# iHIM: Intelligent Heads-Up Interface Module

A local-first command center for your own machine. Anything you would otherwise run from a terminal, or from a scattered pile of scripts, becomes a window on one desktop. One Python process on `127.0.0.1:7777` serves all of it. No cloud, no account, no build step.

Today it runs dictation, a meeting recorder, a to-do list and a YouTube transcriber, because those are the things worth not doing by hand. The surface is the point: a widget is one Web Component plus one router, so the next one is a small file rather than a project.

## Stack

- **Backend:** FastAPI, single process, no reloader in normal operation (one process, one PID).
- **Frontend:** native Web Components end to end. Every widget is a custom element; every window subclasses `IhimPanel`. No framework, no bundler, no transpile. The browser loads the source you wrote.
- **State:** per-widget JSON file stores under `data/local/`. Window positions, sizes and icon layout mirror to the server, so every client (browser tab or desktop shell) shares one desktop.
- **GPU:** dictation always wins. Background transcription waits for an idle mic, and unloads its weights mid-job if you start talking.

## Run

```powershell
# canonical (idempotent: no-op if already healthy)
powershell -File scripts\server.ps1 start                 # port 7777
powershell -File scripts\server.ps1 restart -Port 7778    # test instance
powershell -File scripts\server.ps1 status|stop

# direct
python run.py [--port 7777] [--dev]     # --dev = auto-reload, development only
```

- Login autostart: `start_ihim.vbs` in `shell:startup`, or the resume watchdog (`scripts\install-resume-watchdog.ps1`, run once per machine) which also self-heals a dead port after sleep.
- Desktop app: `cd desktop && npm install && npm start` runs the Electron shell, which attaches to a running server or spawns one. `npm run make-shortcut` produces a pinnable branded shortcut.
- Test instances: set `IHIM_STT_AUTOSTART=0` so they never grab the global dictation hotkey or the GPU.
- Logs: `data/server-console.log` (console) and `data/server-lifecycle.log` (start/stop/restart).

## Layout

```
run.py / run_silent.py     entry + silent shim (startup .vbs contract)
scripts/server.ps1         the ONLY start/stop/restart/status tool
api/
  main.py                  app factory, explicit router registration
  runtime.py middleware.py errors.py responses.py site.py server.py
  stt/ recorder/         dictation + meeting recorder (shared whisper core)
  yt/ preferences.py todos.py
tools/stt/               dictation engine (hotkey -> capture -> transcribe -> inject)
data/local/                per-widget file stores (todos.json, yt/ job sidecars,
                           meeting JSON-LD written by the recorder)
desktop/                   thin Electron shell (attach or spawn, tray, watchdog)
ui/                        index.html + static/js (components/ = all widgets) + style.css
tests/                     pytest
```

## Widgets

- **Dictation** (speech to text): hold a chord, talk, text lands in the focused field. History, copy, correction and a custom vocabulary; live status over SSE. The engine subsystem is named `stt` in paths and APIs.
- **Meeting Recorder:** captures mic and system audio, transcribes locally, writes a self-contained JSON-LD record per meeting. The taskbar chip carries a red outline while recording.
- **To-Do:** quick-capture list grouped by category.
- **YouTube Transcriber:** queue a URL, get a local transcript. FIFO queue, one GPU job at a time, transcript text copied out by path.
- **CPU/RAM bar** and a Windows-style **taskbar**: one chip per open window, click to minimize or restore, drag to reorder, state persists across reloads.
- **Options menu** (top right): screen-level actions such as Restart Server.

## Architecture notes

- **Zero WebSockets.** Dictation status is SSE (`/api/stt/status/stream`); everything else polls. Nothing to leak or drop.
- Errors are RFC 9457 `application/problem+json`. Successes use `{"success": true}` envelopes.
- Security headers on every response, including a report-only CSP while the UI stabilizes.
- Cache busting without a build: a per-boot `BOOT_ID` importmap plus a 3s `/api/boot-id` poll, so edits under `ui/` reload the page without restarting the server.
- The desktop surface never scrolls. Scrolling lives inside windows only, and icon positions are stored as fractions of the desktop's usable travel so a resize preserves the layout.

## Tests

```powershell
python -m pytest        # route, guard and dictation-engine tests
```
