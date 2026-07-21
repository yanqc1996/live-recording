const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('liveRecorderDesktop', {
  platform: process.platform,
  loginDouyin: () => ipcRenderer.invoke('douyin:login'),
  logoutDouyin: () => ipcRenderer.invoke('douyin:logout'),
  getDouyinStatus: () => ipcRenderer.invoke('douyin:status'),
  refreshDouyinSecurity: (roomUrl) => ipcRenderer.invoke('douyin:refresh-security', roomUrl),
  chooseOutputDirectory: () => ipcRenderer.invoke('dialog:output-directory'),
  onDouyinStatusChanged: (callback) => {
    const handler = (_event, status) => callback(status);
    ipcRenderer.on('douyin:status-changed', handler);
    return () => ipcRenderer.removeListener('douyin:status-changed', handler);
  }
});
