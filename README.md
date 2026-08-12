# iHIM: Intelligent Heads-Up Interface Module

iHIM is a dashboard of custom apps.

It's an Electron app that runs off a local Python server. It's built for Windows: the lifecycle scripts are PowerShell, and the dictation hotkey and audio capture hook into Windows directly.

Each app is a Web Component with an API behind it. Any local tool or script can live here. My dictation app, meeting recorder, and YouTube transcriber all run Whisper locally. Another app wraps the two scripts I use to move work between machines on an external drive.

![demo](docs/demo.gif)

## Stack

- The iHIM app is a thin Electron shell that attaches to a running server or spawns one.
- One FastAPI process serves everything.
- The frontend is native Web Components (part of the WHATWG HTML and DOM standards). Every app is a custom element and every window subclasses `IhimPanel`.
- Each app keeps its data in JSON files under `data/local/`. Window layout is saved through the API, so the dashboard comes back in the same state as you left it.

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
run.py                     entry point
scripts/server.ps1         the ONLY start/stop/restart/status tool
api/
  main.py                  app factory, explicit router registration
  runtime.py middleware.py errors.py responses.py site.py server.py
  stt/ recorder/         dictation + meeting recorder (shared whisper core)
  yt/ preferences.py todos.py
tools/stt/               dictation engine (hotkey -> capture -> transcribe -> inject)
data/local/                per-app file stores (todos.json, yt/ job sidecars,
                           meeting JSON-LD written by the recorder)
desktop/                   thin Electron shell (attach or spawn, tray, watchdog)
ui/                        index.html + static/js (components/ = all apps) + style.css
tests/                     pytest
```

## Apps

- **Dictation** (speech to text): hold a chord, talk, and the text lands in the focused field. It keeps a history and takes corrections. A custom vocabulary tunes the transcription, and live status streams over SSE.
- **Meeting Recorder:** captures mic and system audio, transcribes locally, writes a self-contained JSON-LD record per meeting.
- **To-Do:** quick-capture list grouped by category.
- **YouTube Transcriber:** queue a URL, get a local transcript, and the transcript text is copied out by path.
- **Sneakernet:** two buttons over the scripts for moving work between machines on an external drive. Leaving refreshes the drive and ejects it; Returning pulls the work back in.

## Also on screen

- A Windows-style taskbar carries one chip per open app. Click a chip to minimize or restore, drag to reorder, and the state persists across reloads.
- A CPU/RAM widget sits in the same bar.
- **Options menu** (bottom left): screen-level actions such as Restart Server.

## Architecture notes

- Every Whisper load is budgeted against free VRAM. The loader reads what the GPU has left and steps down through smaller compute types. If nothing fits, it falls back to the CPU instead of running out of memory, so a second job costs speed rather than crashing.
- Transcription doesn't wait for a whole recording. Dictation and YouTube jobs both transcribe in chunks while the audio is still coming in, so releasing the chord only leaves the last window to run and a long video's transcript fills in as it goes.
- Errors are RFC 9457 `application/problem+json`. Successes use `{"success": true}` envelopes.
- Security headers on every response, including a report-only CSP.
- Cache busting is a per-boot `BOOT_ID` importmap plus a 3s `/api/boot-id` poll. Edit anything under `ui/` and the page reloads while the server keeps running.
- Scrolling lives inside windows. Icon positions are stored as fractions of the dashboard's usable travel, so a resize preserves the layout.

## Tests

```powershell
python -m pytest        # 105 tests: routes, guards, dictation engine, streaming, recovery
```
