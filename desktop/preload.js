// One narrow bridge: lets the local "down" page (and the server UI, harmlessly)
// ask the shell to restart the backend. Nothing else crosses the boundary.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('ihimShell', {
  restartBackend: () => ipcRenderer.invoke('backend-restart'),
  isBackendUp: () => ipcRenderer.invoke('backend-up'),
});
