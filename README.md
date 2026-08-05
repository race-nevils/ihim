# iHIM: Intelligent Heads-Up Interface Module

A personal app platform and control plane for local tooling. Each tool runs as a widget in its own window on a browser desktop, and one Python process on localhost serves all of it.

A widget is a Web Component with an API behind it. Any local tool or script can live here. My dictation app, meeting recorder, and YouTube transcriber all run Whisper locally. Another widget wraps the two scripts I use to move work between machines on an external drive.

## Stack

- **Backend:** FastAPI on a single process with a stable PID. The reloader is a development flag.
- **Frontend:** native Web Components end to end. Every widget is a custom element; every window subclasses `IhimPanel`. The browser loads the source files straight from the repo.
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
- Test instances: set `IHIM_STT_AUTOSTART=0` to leave the global dictation hotkey and the GPU to the main instance.
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

- **Dictation** (speech to text): hold a chord, talk, text lands in the focused field. History, copy, correction and a custom vocabulary, with live status over SSE.
- **Meeting Recorder:** captures mic and system audio, transcribes locally, writes a self-contained JSON-LD record per meeting. The taskbar chip carries a red outline while recording.
- **To-Do:** quick-capture list grouped by category.
- **YouTube Transcriber:** queue a URL, get a local transcript. FIFO queue, one GPU job at a time, transcript text copied out by path.
- **Sneakernet:** two buttons over the scripts for moving work between machines on an external drive. Leaving refreshes the drive and ejects it; Returning pulls the work back in. Each asks for confirmation, then launches its script in its own console, so that console is the feedback.
- **CPU/RAM bar** and a Windows-style **taskbar**: one chip per open window, click to minimize or restore, drag to reorder, state persists across reloads.
- **Options menu** (top right): screen-level actions such as Restart Server.

## Architecture notes

- **Push is SSE.** Dictation status streams from `/api/stt/status/stream`; everything else polls.
- Errors are RFC 9457 `application/problem+json`. Successes use `{"success": true}` envelopes.
- Security headers on every response, including a report-only CSP.
- Cache busting: a per-boot `BOOT_ID` importmap plus a 3s `/api/boot-id` poll. Edits under `ui/` reload the page while the server keeps running.
- Scrolling lives inside windows. Icon positions are stored as fractions of the desktop's usable travel, so a resize preserves the layout.

## Tests

```powershell
python -m pytest        # route, guard and dictation-engine tests
```
