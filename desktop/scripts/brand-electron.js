// Brand this tree's downloaded electron.exe so the desktop shell shows as
// "iHIM" — not "Electron" — in the Windows Task Manager and taskbar, with the
// arc-reactor mark as its icon.
//
// Why this exists: in dev mode the shell runs the stock, unbranded
// node_modules/electron/dist/electron.exe. Windows reads a process's name from
// that exe's embedded FileDescription resource and its taskbar/pinned icon from
// the exe's icon resource. app.setName() / setAppUserModelId() CANNOT change
// either in dev mode — only rewriting the exe's resources does (grounded:
// Electron's Application-Distribution docs + electron/rcedit). We rewrite them
// with rcedit (its binary is vendored by the `rcedit` devDependency).
//
// Runs as `postinstall` (a fresh/upgraded electron download is unbranded → this
// re-applies it) and again from the launcher. Idempotent via a marker file, a
// no-op off Windows, and non-fatal if a running instance has the exe locked
// (it retries on the next install/launch).

const path = require('path');
const fs = require('fs');
const { execFileSync } = require('child_process');

const DESKTOP = path.resolve(__dirname, '..');
const EXE = path.join(DESKTOP, 'node_modules', 'electron', 'dist', 'electron.exe');
const ICON = path.join(DESKTOP, 'assets', 'icon.ico');
const MARKER = path.join(DESKTOP, 'node_modules', 'electron', 'dist', '.ihim-branded');
const NAME = 'iHIM';

const log = (m) => console.log(`[brand-electron] ${m}`);

function rceditBin() {
  const exe = process.arch === 'ia32' ? 'rcedit.exe' : 'rcedit-x64.exe';
  return path.join(DESKTOP, 'node_modules', 'rcedit', 'bin', exe);
}

// The exe is re-downloaded whenever electron is (re)installed or version-bumped,
// wiping this marker with it. So keying the marker on the icon's identity alone
// is enough: same icon + marker present ⇒ already branded ⇒ skip.
function iconStamp() {
  const s = fs.statSync(ICON);
  return `${s.size}:${Math.round(s.mtimeMs)}`;
}

function main() {
  if (process.platform !== 'win32') return log('non-Windows — skipping');
  if (!fs.existsSync(EXE)) return log('electron.exe not present yet — skipping');
  if (!fs.existsSync(ICON)) return log('assets/icon.ico missing — skipping');

  const stamp = iconStamp();
  try {
    if (fs.readFileSync(MARKER, 'utf8').trim() === stamp) return log('already branded — skipping');
  } catch { /* no marker yet → brand */ }

  const bin = rceditBin();
  if (!fs.existsSync(bin)) return log('rcedit binary missing — skipping');

  try {
    execFileSync(bin, [
      EXE,
      '--set-icon', ICON,
      '--set-version-string', 'FileDescription', NAME,
      '--set-version-string', 'ProductName', NAME,
      '--set-version-string', 'InternalName', NAME,
      '--set-version-string', 'OriginalFilename', 'iHIM.exe',
      '--set-version-string', 'CompanyName', 'EdgeFlow AI',
    ], { stdio: 'pipe' });
  } catch (e) {
    // Almost always: the exe is locked by a running instance. Non-fatal — the
    // next install/launch (with no instance up) will apply it.
    const first = ((e.stderr && e.stderr.toString()) || e.message || '').trim().split('\n')[0];
    return log(`could not write exe (${first || 'locked?'}) — will retry next launch`);
  }

  try { fs.writeFileSync(MARKER, stamp); } catch { /* marker is an optimization */ }
  clearMuiCache();
  log(`electron.exe branded as "${NAME}" (icon + Task Manager name)`);
}

// Task Manager caches a process's friendly name in HKCU\...\Shell\MuiCache,
// keyed by the exe's full path. A stale "Electron" entry from earlier runs can
// survive the resource rewrite. Drop just this exe's cache values so the new
// name shows immediately; Windows rebuilds them on next launch. Best-effort.
function clearMuiCache() {
  const KEY = 'HKCU\\Software\\Classes\\Local Settings\\Software\\Microsoft\\Windows\\Shell\\MuiCache';
  for (const suffix of ['FriendlyAppName', 'ApplicationCompany']) {
    try {
      execFileSync('reg', ['delete', KEY, '/v', `${EXE}.${suffix}`, '/f'], { stdio: 'pipe' });
    } catch { /* value absent (fresh exe path) — fine */ }
  }
}

main();
