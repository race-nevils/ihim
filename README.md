# iHIM: Intelligent Heads-Up Interface Module

iHIM is a dashboard of custom tools, each running as a widget in its own window. It's an Electron desktop app served end to end by one Python process on localhost.

A widget is a Web Component with an API behind it. Any local tool or script can live here. My dictation app, meeting recorder, and YouTube transcriber all run Whisper locally. Another widget wraps the two scripts I use to move work between machines on an external drive.

## Stack

- A thin Electron shell is the app. It attaches to a running server or spawns one, and carries the tray icon and watchdog.
- FastAPI backend. One Python process with a stable PID.
- Native Web Components frontend with no build step. Every widget is a custom element, every window subclasses `IhimPanel`, and the files on disk are the files the app runs.
- Widget data lives in JSON files under `data/local/`. Window layout is saved through the API, so the dashboard comes back exactly as you left it.

## Run

```powershell
# the app
cd desktop && npm install && npm start    # attaches to a running server or spawns one
npm run make-shortcut                     # pinnable branded shortcut

# server on its own (idempotent: no-op if already healthy)
powershell -File scripts\server.ps1 start                 # port 7777
powershell -File scripts\server.ps1 restart -Port 7778    # test instance
powershell -File scripts\server.ps1 status|stop

# direct
python run.py [--port 7777] [--dev]     # --dev = auto-reload, development only
```

- Autostart + self-heal: `scripts\install-resume-watchdog.ps1` (run once per machine) registers a task that starts the server at logon, after sleep, and hourly.
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

- One GPU, and dictation always wins. Background transcription waits for an idle mic and unloads its weights mid-job if you start talking.
- **Push is SSE.** Dictation status streams from `/api/stt/status/stream`; everything else polls.
- Errors are RFC 9457 `application/problem+json`. Successes use `{"success": true}` envelopes.
- Security headers on every response, including a report-only CSP.
- Cache busting: a per-boot `BOOT_ID` importmap plus a 3s `/api/boot-id` poll. Edits under `ui/` reload the page while the server keeps running.
- Scrolling lives inside windows. Icon positions are stored as fractions of the dashboard's usable travel, so a resize preserves the layout.

## Tests

```powershell
python -m pytest        # route, guard and dictation-engine tests
```
