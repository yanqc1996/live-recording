const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('liveRecorderDesktop', {
  platform: process.platform,
  getBackgroundSettings: () => ipcRenderer.invoke('background:get-settings'),
  saveBackgroundSettings: (settings) => ipcRenderer.invoke('background:save-settings', settings),
  loginDouyin: () => ipcRenderer.invoke('douyin:login'),
  importDouyinCookie: (cookie) => ipcRenderer.invoke('douyin:import-cookie', cookie),
  logoutDouyin: () => ipcRenderer.invoke('douyin:logout'),
  getDouyinStatus: () => ipcRenderer.invoke('douyin:status'),
  refreshDouyinSecurity: (roomUrl) => ipcRenderer.invoke('douyin:refresh-security', roomUrl),
  chooseOutputDirectory: () => ipcRenderer.invoke('dialog:output-directory'),
  openExternal: (url) => ipcRenderer.invoke('shell:open-external', url),
  setCompactMode: (enabled) => ipcRenderer.invoke('window:compact-mode', Boolean(enabled)),
  onDouyinStatusChanged: (callback) => {
    const handler = (_event, status) => callback(status);
    ipcRenderer.on('douyin:status-changed', handler);
    return () => ipcRenderer.removeListener('douyin:status-changed', handler);
  }
});
