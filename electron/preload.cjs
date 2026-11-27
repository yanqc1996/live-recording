const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('liveRecorderDesktop', {
  platform: process.platform,
  openMainWindow: () => ipcRenderer.invoke('window:open-main'),
  openMiniControls: () => ipcRenderer.invoke('window:open-mini'),
  closeMiniControls: () => ipcRenderer.invoke('window:close-mini'),
  setMiniExpanded: expanded => ipcRenderer.invoke('window:mini-expanded', Boolean(expanded)),
  getQuickStatus: () => ipcRenderer.invoke('quick:status'),
  resumeAudio: () => ipcRenderer.invoke('audio:resume'),
  onQuickOpen: callback => {
    const handler = () => callback();
    ipcRenderer.on('quick:open', handler);
    return () => ipcRenderer.removeListener('quick:open', handler);
  },
  onAudioRouteChanged: callback => {
    const handler = () => callback();
    ipcRenderer.on('audio:route-changed', handler);
    return () => ipcRenderer.removeListener('audio:route-changed', handler);
  },
  getBackgroundSettings: () => ipcRenderer.invoke('background:get-settings'),
  saveBackgroundSettings: (settings) => ipcRenderer.invoke('background:save-settings', settings),
  loginDouyin: () => ipcRenderer.invoke('douyin:login'),
  importDouyinCookie: (cookie) => ipcRenderer.invoke('douyin:import-cookie', cookie),
  logoutDouyin: () => ipcRenderer.invoke('douyin:logout'),
  getDouyinStatus: () => ipcRenderer.invoke('douyin:status'),
  refreshDouyinSecurity: (roomUrl) => ipcRenderer.invoke('douyin:refresh-security', roomUrl),
  sendDouyinChatHidden: (roomUrl, content) => ipcRenderer.invoke('douyin:send-hidden', roomUrl, content),
  chooseOutputDirectory: () => ipcRenderer.invoke('dialog:output-directory'),
  openExternal: (url) => ipcRenderer.invoke('shell:open-external', url),
  setCompactMode: (enabled) => ipcRenderer.invoke('window:compact-mode', Boolean(enabled)),
  onCompactModeRequested: (callback) => {
    const handler = (_event, enabled) => callback(Boolean(enabled));
    ipcRenderer.on('window:compact-mode-requested', handler);
    return () => ipcRenderer.removeListener('window:compact-mode-requested', handler);
  },
  onDouyinStatusChanged: (callback) => {
    const handler = (_event, status) => callback(status);
    ipcRenderer.on('douyin:status-changed', handler);
    return () => ipcRenderer.removeListener('douyin:status-changed', handler);
  }
});
