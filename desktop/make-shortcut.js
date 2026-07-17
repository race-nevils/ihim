// One-shot installer for the pinnable iHIM shortcut.
//
//   npm run make-shortcut     (or: node_modules\.bin\electron make-shortcut.js)
//
// Writes "iHIM.lnk" to the Start Menu (Programs) and the Desktop:
// target = this tree's electron.exe + this desktop/ app, icon = assets/icon.ico,
// AppUserModelID = the same 'com.ihim.app' main.js sets — that match is what
// makes the pinned taskbar button and the running window merge into one.
// Re-run any time (e.g. after moving trees); it overwrites in place.

const { app, shell } = require('electron');
const path = require('path');

const APP_ID = 'com.ihim.app';
const desktopAppDir = __dirname;

app.whenReady().then(() => {
  const opts = {
    target: process.execPath, // this tree's electron.exe
    args: `"${desktopAppDir}"`,
    cwd: desktopAppDir,
    icon: path.join(desktopAppDir, 'assets', 'icon.ico'),
    iconIndex: 0,
    appUserModelId: APP_ID,
    description: 'iHIM — start backend + open UI (:7777)',
  };

  const targets = [
    path.join(app.getPath('appData'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'iHIM.lnk'),
    path.join(app.getPath('desktop'), 'iHIM.lnk'),
  ];

  let failed = false;
  for (const lnk of targets) {
    const ok = shell.writeShortcutLink(lnk, 'create', opts);
    console.log(`${ok ? 'wrote' : 'FAILED'}: ${lnk}`);
    if (!ok) failed = true;
  }
  app.exit(failed ? 1 : 0);
});
