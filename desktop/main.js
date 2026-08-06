// iHIM — thin desktop shell (same manner as desktop-app/desktop).
//
// The whole app: attach to the iHIM server if it's already up (the usual case —
// the resume watchdog keeps :7777 alive), otherwise start it via
// scripts/server.ps1 (the ONE sanctioned lifecycle tool — identity-verified
// kill, hidden python, console log) and show the server's own UI in a window.
// The server is an always-on service owned by the watchdog task (logon +
// resume + hourly): quitting the shell NEVER stops it — dictation and every
// mesh consumer keep talking to http://127.0.0.1:7777 whether the window is
// open or not. The shell displays, it never proxies.

const { app, BrowserWindow, Tray, Menu, nativeImage, shell, dialog, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// Identify as iHIM, not "Electron". setName drives the userData folder and menu
// label; the AppUserModelID gives us our own taskbar group + icon and correct
// notifications. The Task Manager process NAME and taskbar/pinned ICON come
// from the exe's embedded resources — scripts/brand-electron.js rewrites those
// on the dev electron.exe. Set both here anyway (they're the right half).
app.setName('iHIM');
// MUST equal make-shortcut.js's APP_ID — Windows merges the pinned button and
// the running window into one taskbar item only when the two AUMIDs match.
if (process.platform === 'win32') app.setAppUserModelId('com.ihim.app');

const IHIM_DIR = path.resolve(__dirname, '..');
const LIFECYCLE = path.join(IHIM_DIR, 'scripts', 'server.ps1');
const PORT = parseInt(process.env.IHIM_PORT || '7777', 10);
const BASE = `http://127.0.0.1:${PORT}`;
const STATE_FILE = () => path.join(app.getPath('userData'), 'window-state.json');

// Brand mark (assets/make-icon.py → assets/icon.ico — the ONE icon artifact;
// shortcuts and the branded exe use the same file). Drives the window title-bar
// icon and the tray; the taskbar button uses the branded exe icon.
const ICON = nativeImage.createFromPath(path.join(__dirname, 'assets', 'icon.ico'));

let win = null;
let tray = null;
let watchdog = null;

function isUp() {
  return fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(1500) })
    .then((r) => r.ok)
    .catch(() => false);
}

// server.ps1 start is idempotent (healthy instance already listening → exit 0),
// and its kill path only touches identity-verified iHIM processes.
// stdio MUST be 'ignore', and completion MUST key on 'exit', not stdio close:
// server.ps1 starts the server via Start-Process -Redirect*, which leaks
// inheritable pipe handles into the long-lived python process — a piped stdio
// here would never close, so an execFile-style callback waits forever and the
// shell hangs windowless at the await (holding the single-instance lock).
// Diagnostics live in data\server-lifecycle.log, not in captured output.
function lifecycle(verb) {
  return new Promise((resolve, reject) => {
    const p = spawn(
      'powershell.exe',
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', LIFECYCLE, verb, '-Port', String(PORT)],
      { windowsHide: true, stdio: 'ignore' }
    );
    p.on('error', reject);
    p.on('exit', (code) =>
      code === 0 ? resolve() : reject(new Error(`${verb}: server.ps1 exited ${code} — see IHIM\\data\\server-lifecycle.log`))
    );
  });
}

async function waitUp(tries = 60, delayMs = 250) {
  for (let i = 0; i < tries; i++) {
    if (await isUp()) return true;
    await new Promise((r) => setTimeout(r, delayMs));
  }
  return false;
}

function loadBounds() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE(), 'utf8')); }
  catch { return { width: 1400, height: 900 }; }
}

function createWindow() {
  win = new BrowserWindow({
    ...loadBounds(),
    icon: ICON,
    autoHideMenuBar: true,
    // Hidden title bar + a UI-drawn strip: the page
    // renders its own 36px top bar (shell-only — the browser never shows it;
    // see [data-shell] in style.css) as the SAME flat opaque color as this
    // overlay, so the native min/max/close cluster sits seamlessly on the
    // bar — the overlay is an OS-painted flat rectangle, so any gradient or
    // translucency in the page strip makes it read as a separate box.
    // No icon, no caption text. Recoloring the NATIVE framed caption via DWM
    // was tried first and abandoned — Chromium re-asserts its own frame
    // color on activation/minimize, so the paint didn't survive.
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#0e0d0d', symbolColor: '#cdd6f4', height: 36 },
    backgroundColor: '#11111b',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });

  // Keep the window pinned to the app origin — limit navigation + control
  // window creation. Origin comparison via URL parse (a startsWith prefix
  // check is bypassable: http://127.0.0.1:7777@evil.com parses BASE as
  // userinfo). Anything else opens in the OS browser, but only http/https —
  // shell.openExternal on arbitrary schemes (file://, ms-msdt:) launches
  // native handlers. Programmatic loadFile/loadURL (the down-page swap) never
  // fires will-navigate, so no file:// allowance is needed.
  const sameOrigin = (t) => { try { return new URL(t).origin === BASE; } catch { return false; } };
  const openable = (t) => { try { return ['http:', 'https:'].includes(new URL(t).protocol); } catch { return false; } };
  win.webContents.on('will-navigate', (e, target) => {
    if (sameOrigin(target)) return;
    e.preventDefault();
    if (openable(target)) shell.openExternal(target);
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (!sameOrigin(url) && openable(url)) shell.openExternal(url);
    return { action: 'deny' };
  });

  win.loadURL(BASE);
  win.on('close', () => {
    try { fs.writeFileSync(STATE_FILE(), JSON.stringify(win.getBounds())); } catch {}
  });
  win.on('closed', () => { win = null; });
}

async function restartBackend() {
  try { await lifecycle('restart'); } catch (e) { dialog.showErrorBox('Restart failed', String(e.message)); return; }
  await waitUp();
  if (win) win.loadURL(BASE);
}

// If the backend stops answering, swap to the local "down" page; it polls
// health through the shell bridge and returns to the server UI once it's back.
// (The port-ensure hook restarts :7777 after any iHIM code edit — this is
// what makes the window ride through those restarts.)
function startWatchdog() {
  let fails = 0;
  watchdog = setInterval(async () => {
    if (!win) return;
    if (await isUp()) { fails = 0; return; }
    fails += 1;
    if (fails === 2 && win.webContents.getURL().startsWith(BASE)) {
      win.loadFile(path.join(__dirname, 'down.html'), { query: { base: BASE } });
    }
  }, 5000);
}

function buildMenus() {
  const items = [
    { label: 'Show', click: () => { if (win) { win.show(); win.focus(); } } },
    { label: 'Restart Backend', click: restartBackend },
    { label: 'Open in Browser', click: () => shell.openExternal(BASE) },
    { type: 'separator' },
    { label: 'Quit', click: () => app.quit() },
  ];
  tray = new Tray(ICON);
  tray.setToolTip(`iHIM — ${BASE}`);
  tray.setContextMenu(Menu.buildFromTemplate(items));
  tray.on('double-click', () => { if (win) { win.show(); win.focus(); } });

  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: 'App',
      submenu: [
        { label: 'Reload UI', accelerator: 'CmdOrCtrl+R', click: () => { if (win) win.loadURL(BASE); } },
        { label: 'DevTools', accelerator: 'F12', click: () => { if (win) win.webContents.toggleDevTools(); } },
        { label: 'Restart Backend', accelerator: 'CmdOrCtrl+Shift+R', click: restartBackend },
        { role: 'quit' },
      ],
    },
  ]));
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => { if (win) { win.show(); win.focus(); } });

  ipcMain.handle('backend-restart', restartBackend);
  // The down page can't poll the server itself (file:// origin → CORS +
  // Fetch-Metadata refusal), so the main process answers on its behalf.
  ipcMain.handle('backend-up', () => isUp());

  app.whenReady().then(async () => {
    if (!(await isUp())) {
      try { await lifecycle('start'); } catch (e) {
        dialog.showErrorBox('iHIM', `Backend failed to start.\n\n${e.message}`);
        app.exit(1);
        return;
      }
      if (!(await waitUp())) {
        dialog.showErrorBox('iHIM', `Backend never became healthy at ${BASE}.\nCheck IHIM\\data\\server-console.log`);
        app.exit(1);
        return;
      }
    }
    createWindow();
    buildMenus();
    startWatchdog();
  });

  // Quit is window-only: the watchdog task owns the server's lifecycle, so
  // closing the shell must leave :7777 (and the dictation hotkey) running.
  app.on('window-all-closed', () => app.quit());
}
