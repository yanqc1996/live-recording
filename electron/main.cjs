const { app, BrowserWindow, dialog, globalShortcut, ipcMain, Menu, nativeImage, Notification, powerMonitor, powerSaveBlocker, screen, session, shell, Tray } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { LOGIN_COOKIE_NAMES, parseCookieHeader } = require('./douyin-cookie.cjs');

const DOUYIN_PARTITION = 'persist:douyin-auth';
const DOUYIN_LOGIN_URL = 'https://www.douyin.com/';

// Keep the existing data location while presenting a discreet English app name.
app.setPath('userData', path.join(app.getPath('appData'), '播录助手'));
app.setName('Live Studio');

let mainWindow = null;
let miniWindow = null;
let loginWindow = null;
let senderWindow = null;
let senderQueue = Promise.resolve();
let lastDouyinChatSentAt = 0;
let backend = null;
let backendUrl = '';
let backendToken = '';
let quitting = false;
let quitCheckInProgress = false;
let syncTimer = null;
let douyinSecurity = {};
let normalWindowBounds = null;
let compactMode = false;
let windowStateTimer = null;
let tray = null;
let trayRefreshTimer = null;
let trayState = null;
let powerBlockerId = null;
let notificationSnapshot = null;
const activeNotifications = new Set();

const BACKGROUND_DEFAULTS = {
  open_at_login: false,
  launch_hidden: true,
  hide_dock_when_background: true,
  auto_start_recording: false,
  anonymous_live_access: true,
  prevent_sleep_when_active: true,
  notify_recording: false,
  notify_upload: false,
  notify_errors: false
};

function backgroundSettingsPath() {
  return path.join(app.getPath('userData'), 'background-settings.json');
}

function loadBackgroundSettings() {
  try {
    const value = JSON.parse(fs.readFileSync(backgroundSettingsPath(), 'utf8'));
    return { ...BACKGROUND_DEFAULTS, ...(value && typeof value === 'object' ? value : {}) };
  } catch {
    return { ...BACKGROUND_DEFAULTS };
  }
}

function applyLoginItemSettings(settings) {
  if (process.platform !== 'darwin') return;
  app.setLoginItemSettings({
    openAtLogin: Boolean(settings.open_at_login),
    openAsHidden: Boolean(settings.launch_hidden),
    args: settings.launch_hidden ? ['--background'] : []
  });
}

function saveBackgroundSettings(supplied) {
  const current = loadBackgroundSettings();
  const settings = { ...current };
  for (const key of Object.keys(BACKGROUND_DEFAULTS)) {
    if (key in supplied) settings[key] = Boolean(supplied[key]);
  }
  const temporary = `${backgroundSettingsPath()}.tmp`;
  fs.mkdirSync(path.dirname(backgroundSettingsPath()), { recursive: true });
  fs.writeFileSync(temporary, JSON.stringify(settings, null, 2), 'utf8');
  fs.renameSync(temporary, backgroundSettingsPath());
  applyLoginItemSettings(settings);
  updatePowerBlocker(trayState);
  if (backendUrl) postBackend('/api/auth/live-access', { anonymous: settings.anonymous_live_access }).catch(console.error);
  return settings;
}

function shouldLaunchHidden() {
  if (!loadBackgroundSettings().launch_hidden) return false;
  const login = process.platform === 'darwin' ? app.getLoginItemSettings() : {};
  return process.argv.includes('--background') || Boolean(login.wasOpenedAtLogin || login.wasOpenedAsHidden);
}

function updatePowerBlocker(state) {
  const settings = loadBackgroundSettings();
  const uploads = state?.baidupan || {};
  const interaction = state?.interaction || {};
  const active = Boolean(
    state?.status?.running ||
    interaction.listening ||
    interaction.audio_playing ||
    Number(uploads.pending || 0) > 0
  );
  if (settings.prevent_sleep_when_active && active) {
    if (powerBlockerId == null || !powerSaveBlocker.isStarted(powerBlockerId)) {
      powerBlockerId = powerSaveBlocker.start('prevent-app-suspension');
    }
  } else if (powerBlockerId != null && powerSaveBlocker.isStarted(powerBlockerId)) {
    powerSaveBlocker.stop(powerBlockerId);
    powerBlockerId = null;
  }
}

function showSystemNotification(title, body) {
  if (!Notification.isSupported()) return;
  const notification = new Notification({ title, body, silent: false });
  activeNotifications.add(notification);
  notification.on('click', showMainWindow);
  notification.on('close', () => activeNotifications.delete(notification));
  notification.show();
}

function processStateNotifications(state) {
  const settings = loadBackgroundSettings();
  const rooms = state?.status?.room_states || {};
  const queue = state?.baidupan?.queue || [];
  const next = {
    rooms: Object.fromEntries(Object.entries(rooms).map(([name, item]) => [name, item.state || 'waiting'])),
    uploads: Object.fromEntries(queue.map((item) => [item.id, item.status]))
  };
  if (!notificationSnapshot) {
    notificationSnapshot = next;
    return;
  }
  if (settings.notify_recording) {
    for (const [anchorId, room] of Object.entries(rooms)) {
      const before = notificationSnapshot.rooms[anchorId];
      const name = room.name || anchorId;
      if (room.state === 'recording' && before !== 'recording') {
        showSystemNotification('Live session detected', `Recording ${name}${room.path ? `\n${path.basename(room.path)}` : ''}`);
      } else if (before === 'recording' && room.state !== 'recording') {
        showSystemNotification('Recording completed', `${name} was saved and queued for processing.`);
      }
    }
  }
  for (const item of queue) {
    const before = notificationSnapshot.uploads[item.id];
    if (!before || before === item.status) continue;
    const name = item.record_name || path.basename(item.save_file_path || '') || 'Recording';
    if (item.status === 'success' && settings.notify_upload) {
      showSystemNotification('Cloud archive completed', `${name} was uploaded successfully.`);
    } else if (item.status === 'failed' && settings.notify_errors) {
      showSystemNotification('Cloud upload failed', `${name} can be retried from the upload queue.`);
    }
  }
  notificationSnapshot = next;
}

function windowStatePath() {
  return path.join(app.getPath('userData'), 'window-state.json');
}

function loadWindowState() {
  try {
    const value = JSON.parse(fs.readFileSync(windowStatePath(), 'utf8'));
    return value && typeof value === 'object' ? value : {};
  } catch {
    return {};
  }
}

function saveWindowState(patch) {
  const temporary = `${windowStatePath()}.tmp`;
  const next = { ...loadWindowState(), ...patch };
  fs.mkdirSync(path.dirname(windowStatePath()), { recursive: true });
  fs.writeFileSync(temporary, JSON.stringify(next), 'utf8');
  fs.renameSync(temporary, windowStatePath());
  return next;
}

function saveCompactWindowBounds() {
  if (!mainWindow || !compactMode || mainWindow.isDestroyed()) return;
  clearTimeout(windowStateTimer);
  windowStateTimer = setTimeout(() => {
    if (!mainWindow || !compactMode || mainWindow.isDestroyed()) return;
    const { x, y, width, height } = mainWindow.getBounds();
    saveWindowState({ compact: { x, y, width, height } });
  }, 250);
}

function compactBounds(saved, fallback) {
  const width = Math.max(390, Math.min(680, Number(saved.width) || 430));
  const height = Math.max(560, Math.min(900, Number(saved.height) || 720));
  const candidate = {
    x: Number.isFinite(saved.x) ? saved.x : fallback.x + Math.max(0, fallback.width - width),
    y: Number.isFinite(saved.y) ? saved.y : fallback.y,
    width,
    height
  };
  const area = screen.getDisplayMatching(candidate).workArea;
  return {
    ...candidate,
    x: Math.max(area.x, Math.min(candidate.x, area.x + area.width - width)),
    y: Math.max(area.y, Math.min(candidate.y, area.y + area.height - height))
  };
}

function allowedDouyinUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    return url.protocol === 'https:' && (url.hostname === 'douyin.com' || url.hostname.endsWith('.douyin.com'));
  } catch {
    return false;
  }
}

function validateMainSender(event) {
  if (!mainWindow || event.sender.id !== mainWindow.webContents.id) throw new Error('Invalid IPC sender');
  const url = new URL(event.senderFrame.url);
  if (url.hostname !== '127.0.0.1') throw new Error('Invalid IPC origin');
}

function validateAppSender(event) {
  const trusted = [mainWindow, miniWindow].some((window) => window && !window.isDestroyed() && event.sender.id === window.webContents.id);
  if (!trusted) throw new Error('Invalid IPC sender');
  const url = new URL(event.senderFrame.url);
  if (url.hostname !== '127.0.0.1') throw new Error('Invalid IPC origin');
}

function sourceRoot() {
  return path.join(__dirname, '..');
}

function prepareEngineRoot() {
  if (!app.isPackaged) return sourceRoot();
  const target = path.join(app.getPath('userData'), 'engine');
  fs.mkdirSync(target, { recursive: true });
  const configDir = path.join(target, 'config');
  fs.mkdirSync(configDir, { recursive: true });
  const configFile = path.join(configDir, 'config.ini');
  const roomsFile = path.join(configDir, 'URL_config.ini');
  if (!fs.existsSync(configFile)) fs.copyFileSync(path.join(process.resourcesPath, 'defaults', 'config.default.ini'), configFile);
  if (!fs.existsSync(roomsFile)) fs.writeFileSync(roomsFile, '', 'utf8');
  return target;
}

function pythonCommand() {
  if (process.env.LIVERECORDER_PYTHON) return process.env.LIVERECORDER_PYTHON;
  return process.platform === 'win32' ? 'python' : 'python3';
}

function packagedRuntime() {
  const executable = process.platform === 'win32' ? 'LiveRecorderRuntime.exe' : 'LiveRecorderRuntime';
  return path.join(process.resourcesPath, 'runtime', 'LiveRecorderRuntime', executable);
}

function buildCommit() {
  const buildInfo = app.isPackaged
    ? path.join(process.resourcesPath, 'build-info.json')
    : path.join(sourceRoot(), 'build', 'generated', 'build-info.json');
  try {
    const value = JSON.parse(fs.readFileSync(buildInfo, 'utf8')).commit;
    return String(value || '').slice(0, 12);
  } catch {
    return 'development';
  }
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const engineRoot = prepareEngineRoot();
    const readyFile = path.join(app.getPath('userData'), `backend-ready-${process.pid}.txt`);
    try { fs.rmSync(readyFile, { force: true }); } catch {}
    const runtime = app.isPackaged ? packagedRuntime() : pythonCommand();
    const args = app.isPackaged ? ['--port', '0', '--no-browser', '--ready-file', readyFile] : [
      '-u', 'desktop_app.py', '--port', '0', '--no-browser', '--ready-file', readyFile
    ];
    const runtimeBin = app.isPackaged ? path.join(process.resourcesPath, 'runtime', 'bin') : '';
    const environment = {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      LIVERECORDER_DATA_ROOT: engineRoot,
      BOLU_APP_VERSION: app.getVersion(),
      BOLU_BUILD_COMMIT: buildCommit()
    };
    if (app.isPackaged) {
      environment.LIVERECORDER_ENGINE_EXECUTABLE = runtime;
      environment.PATH = `${runtimeBin}${path.delimiter}${environment.PATH || ''}`;
    }
    backend = spawn(runtime, args, {
      cwd: engineRoot,
      windowsHide: true,
      env: environment
    });
    let settled = false;
    let timeout = null;
    let poller = null;
    const finish = (url) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      clearInterval(poller);
      backendUrl = url;
      backendToken = new URL(backendUrl).searchParams.get('token') || '';
      resolve();
    };
    const fail = (message) => {
      if (!settled) {
        settled = true;
        clearTimeout(timeout);
        clearInterval(poller);
        reject(new Error(message));
      }
    };
    backend.on('error', (error) => fail(`Unable to start the recording engine: ${error.message}`));
    backend.on('exit', (code) => {
      if (!quitting) fail(`Recording engine exited unexpectedly (${code ?? 'unknown'})`);
    });
    backend.stdout.on('data', (chunk) => {
      const output = chunk.toString();
      const match = output.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[A-Za-z0-9_-]+/);
      if (match) finish(match[0]);
    });
    backend.stderr.on('data', (chunk) => console.error(chunk.toString()));
    poller = setInterval(() => {
      try {
        if (!fs.existsSync(readyFile)) return;
        const url = fs.readFileSync(readyFile, 'utf8').trim();
        if (/^http:\/\/127\.0\.0\.1:\d+\/\?token=[A-Za-z0-9_-]+$/.test(url)) finish(url);
      } catch {}
    }, 150);
    timeout = setTimeout(() => fail('Recording engine startup timed out. Please restart the app.'), 45000);
  });
}

async function postBackend(pathname, body) {
  if (!backendUrl) throw new Error('Recording engine is not ready');
  const origin = new URL(backendUrl).origin;
  const response = await fetch(`${origin}${pathname}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-LiveRecorder-Token': backendToken },
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error((await response.json()).error || 'Local service request failed');
  return response.json();
}

async function backendState() {
  if (!backendUrl) throw new Error('Recording engine is not ready');
  const origin = new URL(backendUrl).origin;
  const response = await fetch(`${origin}/api/state`, {
    headers: { 'X-LiveRecorder-Token': backendToken }
  });
  if (!response.ok) throw new Error((await response.json()).error || 'Unable to read local service status');
  return response.json();
}

async function ensureAutomaticRecording() {
  const settings = loadBackgroundSettings();
  if (!settings.auto_start_recording) return false;
  const state = await backendState();
  if (state.status?.running) return true;
  if (!(state.anchors || []).some((anchor) => anchor.enabled_recording !== false && (anchor.live_url || anchor.web_rid))) {
    throw new Error('Automatic recording is enabled, but no creator has a resolved live room');
  }
  await postBackend('/api/start', { settings: state.settings || {} });
  return true;
}

function showMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (process.platform === 'darwin') app.dock.show();
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function hideMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.hide();
  if (process.platform === 'darwin' && loadBackgroundSettings().hide_dock_when_background) app.dock.hide();
}

async function openCompactWindow() {
  showMainWindow();
  mainWindow.webContents.send('window:compact-mode-requested', true);
}

function miniBounds(saved = {}) {
  const width = 336;
  const height = 58;
  const area = screen.getDisplayNearestPoint(screen.getCursorScreenPoint()).workArea;
  return {
    x: Number.isFinite(saved.x) ? Math.max(area.x, Math.min(saved.x, area.x + area.width - width)) : area.x + area.width - width - 18,
    y: Number.isFinite(saved.y) ? Math.max(area.y, Math.min(saved.y, area.y + area.height - height)) : area.y + 18,
    width,
    height
  };
}

async function openMiniWindow() {
  if (miniWindow && !miniWindow.isDestroyed()) {
    miniWindow.show();
    miniWindow.focus();
    return;
  }
  miniWindow = new BrowserWindow({
    ...miniBounds(loadWindowState().mini || {}),
    minWidth: 336,
    maxWidth: 336,
    minHeight: 58,
    maxHeight: 540,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      backgroundThrottling: false
    }
  });
  miniWindow.setAlwaysOnTop(true, 'floating');
  miniWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  miniWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  miniWindow.webContents.on('will-navigate', (event, url) => {
    if (url !== `${backendUrl}&mini=1`) event.preventDefault();
  });
  miniWindow.on('moved', () => {
    if (!miniWindow || miniWindow.isDestroyed()) return;
    const { x, y } = miniWindow.getBounds();
    saveWindowState({ mini: { x, y } });
  });
  miniWindow.on('closed', () => { miniWindow = null; });
  await miniWindow.loadURL(`${backendUrl}&mini=1`);
  miniWindow.show();
}

function trayIcon() {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18"><rect x="2" y="3" width="14" height="12" rx="3" fill="black"/><path d="M7 6.2v5.6l4.7-2.8z" fill="white"/><circle cx="14.4" cy="4" r="2.1" fill="black" stroke="white" stroke-width="1"/></svg>';
  const image = nativeImage.createFromDataURL(`data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`);
  image.setTemplateImage(true);
  return image;
}

function rebuildTrayMenu() {
  if (!tray) return;
  const recording = Boolean(trayState?.status?.running);
  const roomStates = Object.values(trayState?.status?.room_states || {});
  const recordingRooms = roomStates.filter((item) => item.state === 'recording').length;
  const uploads = trayState?.baidupan || {};
  const uploading = Array.isArray(uploads.progresses) ? uploads.progresses.length : 0;
  const pending = Number(uploads.pending || 0);
  tray.setToolTip(recording ? `Live Studio · Recording ${recordingRooms || ''}`.trim() : 'Live Studio · Background idle');
  if (process.platform === 'darwin') tray.setTitle(recording ? ' ●' : '');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: recording ? `● Recording${recordingRooms ? ` · ${recordingRooms} rooms` : ''}` : '○ Recorder idle', enabled: false },
    { label: uploading ? `Cloud upload · ${uploading} files` : pending ? `Upload queue · ${pending} tasks` : 'Upload queue idle', enabled: false },
    { type: 'separator' },
    {
      label: recording ? 'Stop & Save' : 'Start Automatic Recording',
      click: async () => {
        try {
          if (recording) await postBackend('/api/stop', {});
          else {
            const state = await backendState();
            await postBackend('/api/start', { settings: state.settings || {} });
          }
          await refreshTray();
        } catch (error) {
          dialog.showErrorBox('Recording action failed', error.message);
        }
      }
    },
    { label: 'Open Floating Controls', click: () => openMiniWindow().catch((error) => dialog.showErrorBox('Unable to open floating controls', error.message)) },
    { label: 'Open Live Studio', click: showMainWindow },
    { label: 'Hide Window', enabled: Boolean(mainWindow?.isVisible()), click: hideMainWindow },
    { type: 'separator' },
    { label: 'Quit Live Studio', click: () => app.quit() }
  ]));
}

async function refreshTray() {
  try {
    trayState = await backendState();
    processStateNotifications(trayState);
  } catch {
    trayState = null;
  }
  updatePowerBlocker(trayState);
  rebuildTrayMenu();
}

function createTray() {
  if (tray) return;
  tray = new Tray(trayIcon());
  rebuildTrayMenu();
  refreshTray().catch(() => {});
  trayRefreshTimer = setInterval(() => refreshTray().catch(() => {}), 3000);
  trayRefreshTimer.unref?.();
}

function normalizeSecurityCandidate(value) {
  if (!value || typeof value !== 'object') return null;
  const ticket = value.ticket || value.bd_ticket || value.bdTicket || '';
  const tsSign = value.ts_sign || value.tsSign || value.bd_ticket_guard_ts_sign || '';
  const privateKey = value.private_key || value.privateKey || value.ec_privateKey || value.ecPrivateKey || '';
  if (ticket && tsSign && privateKey) return { ticket, ts_sign: tsSign, private_key: privateKey };
  return null;
}

function securityStatus() {
  return {
    ticket: Boolean(douyinSecurity.ticket),
    ts_sign: Boolean(douyinSecurity.ts_sign),
    private_key: Boolean(douyinSecurity.private_key),
    complete: Boolean(douyinSecurity.ticket && douyinSecurity.ts_sign && douyinSecurity.private_key)
  };
}

async function collectDouyinSecurity() {
  if (!loginWindow || loginWindow.isDestroyed() || !allowedDouyinUrl(loginWindow.webContents.getURL())) return douyinSecurity;
  try {
    const security = await loginWindow.webContents.executeJavaScript(`
      (() => {
        const out = [];
        const seen = new WeakSet();
        let scanned = 0;
        const push = (value) => {
          if (scanned > 4000 || out.length > 200) return;
          scanned += 1;
          if (value == null) return;
          if (typeof value === 'string') {
            if (!/(ticket|ts_sign|private|ec_privateKey|web_protect|bd-ticket|bd_ticket)/i.test(value)) return;
            try { out.push(JSON.parse(value)); } catch { out.push({ raw: value }); }
            return;
          }
          if (typeof value !== 'object' || seen.has(value)) return;
          seen.add(value);
          out.push(value);
          for (const nested of Object.values(value)) push(nested);
        };
        const read = (store) => {
          for (let i = 0; i < store.length; i += 1) {
            const key = store.key(i);
            const raw = store.getItem(key);
            if (!raw || !/(ticket|ts_sign|private|ec_privateKey|web_protect|bd-ticket)/i.test(key + raw)) continue;
            try { push(JSON.parse(raw)); } catch { out.push({ [key]: raw }); }
          }
        };
        try { read(localStorage); } catch {}
        try { read(sessionStorage); } catch {}
        try {
          for (const key of Object.keys(window)) {
            if (!/(web|protect|ticket|guard|douyin|secsdk|byted)/i.test(key)) continue;
            try { push(window[key]); } catch {}
          }
        } catch {}
        return out;
      })()
    `, true);
    for (const item of security || []) {
      const direct = normalizeSecurityCandidate(item);
      if (direct) {
        douyinSecurity = direct;
        break;
      }
      for (const value of Object.values(item || {})) {
        let parsed = value;
        if (typeof value === 'string') {
          try { parsed = JSON.parse(value); } catch { parsed = null; }
        }
        const nested = normalizeSecurityCandidate(parsed);
        if (nested) {
          douyinSecurity = nested;
          break;
        }
      }
    }
  } catch {
    return douyinSecurity;
  }
  return douyinSecurity;
}

async function refreshDouyinSecurity(roomUrl = '') {
  createLoginWindow();
  const targetUrl = allowedDouyinUrl(roomUrl) ? roomUrl : DOUYIN_LOGIN_URL;
  if (roomUrl && allowedDouyinUrl(targetUrl)) {
    await loginWindow.webContents.loadURL(targetUrl);
  }
  await new Promise((resolve) => setTimeout(resolve, 1800));
  for (let attempt = 0; attempt < 8; attempt += 1) {
    await collectDouyinSecurity();
    await syncDouyinSession();
    if (securityStatus().complete) break;
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  const cookies = await douyinCookies();
  const connected = hasLoginCookie(cookies);
  return {
    connected,
    canSend: connected && securityStatus().complete,
    security: securityStatus()
  };
}

function createHiddenSenderWindow() {
  if (senderWindow && !senderWindow.isDestroyed()) return senderWindow;
  senderWindow = new BrowserWindow({
    width: 960,
    height: 720,
    show: false,
    skipTaskbar: true,
    webPreferences: {
      partition: DOUYIN_PARTITION,
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      backgroundThrottling: false
    }
  });
  senderWindow.webContents.setAudioMuted(true);
  senderWindow.webContents.on('will-navigate', (event, url) => {
    if (!allowedDouyinUrl(url)) event.preventDefault();
  });
  senderWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  senderWindow.on('closed', () => { senderWindow = null; });
  return senderWindow;
}

async function sendDouyinChatHidden(roomUrl, rawContent) {
  if (!allowedDouyinUrl(roomUrl) || !/^https:\/\/live\.douyin\.com\//.test(roomUrl)) {
    throw new Error('请选择有效的抖音直播间');
  }
  const content = String(rawContent || '').trim();
  if (!content) throw new Error('弹幕内容不能为空');
  if (Array.from(content).length > 200) throw new Error('弹幕内容不能超过 200 个字符');
  if (!hasLoginCookie(await douyinCookies())) throw new Error('请先同步已登录的抖音 Cookie');

  const window = createHiddenSenderWindow();
  if (window.webContents.getURL().split('?', 1)[0].replace(/\/$/, '') !== roomUrl.split('?', 1)[0].replace(/\/$/, '')) {
    await window.loadURL(roomUrl);
  }
  // Douyin's live chat uses a Slate editor.  Synthetic DOM input events are
  // frequently ignored by Slate, so focus it in the page and send native
  // keyboard events through Electron instead.
  const chatInputSelector = '[data-e2e="live-chatting"] [data-slate-editor="true"][contenteditable="true"]';
  const fallbackSelectors = [
    'textarea[placeholder*="说点"]',
    'textarea[placeholder*="聊"]',
    '[contenteditable="true"][data-placeholder*="说点"]',
    '[contenteditable="true"][data-e2e*="chat"]',
    '[class*="chatroom"] [contenteditable="true"]'
  ];
  const selectors = JSON.stringify([chatInputSelector, ...fallbackSelectors]);
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const result = await window.webContents.executeJavaScript(`
      (() => {
        const visible = element => {
          const rect = element?.getBoundingClientRect?.();
          const style = element ? getComputedStyle(element) : null;
          return Boolean(rect && rect.width > 0 && rect.height > 0 && style?.visibility !== 'hidden' && style?.display !== 'none');
        };
        const input = ${selectors}.flatMap(selector => Array.from(document.querySelectorAll(selector))).find(visible);
        if (!input) {
          const body = document.body?.innerText || '';
          if (/扫码登录|登录后/.test(body)) return { state: 'login' };
          if (/验证|安全校验|访问频繁/.test(body)) return { state: 'verification' };
          return { state: 'waiting' };
        }
        input.focus();
        return { state: 'ready' };
      })()
    `, true);
    if (result?.state === 'ready') {
      const throttle = lastDouyinChatSentAt + 3000 - Date.now();
      if (throttle > 0) await new Promise(resolve => setTimeout(resolve, throttle));
      const modifier = process.platform === 'darwin' ? 'meta' : 'control';
      window.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'A', modifiers: [modifier] });
      window.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'A', modifiers: [modifier] });
      window.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Backspace' });
      window.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Backspace' });
      window.webContents.insertText(content);
      window.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Enter' });
      window.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Enter' });
      lastDouyinChatSentAt = Date.now();
      await new Promise(resolve => setTimeout(resolve, 500));
      const remaining = await window.webContents.executeJavaScript(`
        (() => {
          const input = ${selectors}.flatMap(selector => Array.from(document.querySelectorAll(selector))).find(element => {
            const rect = element?.getBoundingClientRect?.();
            return Boolean(rect && rect.width > 0 && rect.height > 0);
          });
          return String(input?.value ?? input?.innerText ?? '').replace(/[\\u200B\\s]/g, '');
        })()
      `, true);
      if (!remaining) return { ok: true, mode: 'hidden-page', confirmed: 'input-cleared' };
      window.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'A', modifiers: [modifier] });
      window.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'A', modifiers: [modifier] });
      window.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Backspace' });
      window.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Backspace' });
      throw new Error('弹幕未被直播间接收，可能触发了风控、验证或字数限制');
    }
    if (result?.state === 'login') throw new Error('后台发送会话未登录，请重新同步 Cookie');
    if (result?.state === 'verification') throw new Error('抖音要求安全验证，后台发送已暂停');
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error('直播间弹幕输入框加载超时，请确认主播正在开播且抖音账号已登录');
}

async function douyinCookies() {
  return session.fromPartition(DOUYIN_PARTITION).cookies.get({ domain: 'douyin.com' });
}

function hasLoginCookie(cookies) {
  return cookies.some((cookie) => LOGIN_COOKIE_NAMES.has(cookie.name) && cookie.value && cookie.value !== '0');
}

async function syncDouyinSession() {
  await collectDouyinSecurity();
  const cookies = await douyinCookies();
  const connected = hasLoginCookie(cookies);
  const cookie = connected
    ? cookies.sort((a, b) => a.name.localeCompare(b.name)).map(({ name, value }) => `${name}=${value}`).join('; ')
    : '';
  await postBackend('/api/auth/douyin', {
    cookie,
    security: douyinSecurity,
    anonymous_live_access: loadBackgroundSettings().anonymous_live_access
  });
  const status = { connected, canSend: connected && securityStatus().complete, security: securityStatus() };
  mainWindow?.webContents.send('douyin:status-changed', status);
  return status;
}

function scheduleCookieSync() {
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => syncDouyinSession().catch(console.error), 500);
}

function createLoginWindow() {
  if (loginWindow && !loginWindow.isDestroyed()) {
    loginWindow.focus();
    return;
  }
  const authSession = session.fromPartition(DOUYIN_PARTITION);
  authSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  authSession.setPermissionCheckHandler(() => false);
  authSession.cookies.on('changed', scheduleCookieSync);
  loginWindow = new BrowserWindow({
    width: 1040,
    height: 760,
    minWidth: 760,
    minHeight: 600,
    title: 'Sign in to Douyin',
    parent: mainWindow,
    autoHideMenuBar: true,
    webPreferences: {
      partition: DOUYIN_PARTITION,
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true
    }
  });
  loginWindow.webContents.on('will-navigate', (event, url) => {
    if (!allowedDouyinUrl(url)) event.preventDefault();
  });
  loginWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (allowedDouyinUrl(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  loginWindow.on('closed', () => {
    loginWindow = null;
    syncDouyinSession().catch(console.error);
  });
  loginWindow.loadURL(DOUYIN_LOGIN_URL);
}

async function logoutDouyin() {
  const authSession = session.fromPartition(DOUYIN_PARTITION);
  const cookies = await douyinCookies();
  await Promise.all(cookies.map((cookie) => {
    const domain = (cookie.domain || 'www.douyin.com').replace(/^\./, '');
    const protocol = cookie.secure ? 'https' : 'http';
    return authSession.cookies.remove(`${protocol}://${domain}${cookie.path || '/'}`, cookie.name);
  }));
  await authSession.clearStorageData({ storages: ['localstorage', 'cachestorage', 'serviceworkers'] });
  await authSession.cookies.flushStore();
  douyinSecurity = {};
  return syncDouyinSession();
}

async function importDouyinCookie(rawCookie) {
  const imported = parseCookieHeader(rawCookie);
  const authSession = session.fromPartition(DOUYIN_PARTITION);
  if (loginWindow && !loginWindow.isDestroyed()) {
    loginWindow.removeAllListeners('closed');
    loginWindow.close();
    loginWindow = null;
  }
  const existing = await douyinCookies();
  await Promise.all(existing.map((cookie) => {
    const domain = (cookie.domain || 'www.douyin.com').replace(/^\./, '');
    const protocol = cookie.secure ? 'https' : 'http';
    return authSession.cookies.remove(`${protocol}://${domain}${cookie.path || '/'}`, cookie.name);
  }));
  await authSession.clearStorageData({ storages: ['localstorage', 'cachestorage', 'serviceworkers'] });
  douyinSecurity = {};
  const expirationDate = Math.floor(Date.now() / 1000) + (30 * 24 * 60 * 60);
  await Promise.all(imported.map(({ name, value }) => {
    const cookie = {
      url: DOUYIN_LOGIN_URL,
      name,
      value,
      path: '/',
      secure: true,
      httpOnly: false,
      expirationDate
    };
    if (!name.startsWith('__Host-')) cookie.domain = '.douyin.com';
    return authSession.cookies.set(cookie);
  }));
  await authSession.cookies.flushStore();
  return syncDouyinSession();
}

let audioRouteMonitor = null;
let audioGuardReady = false;
function startAudioRouteMonitor() {
  if (process.platform !== 'darwin') return;
  const executable = require('node:path').join(__dirname.replace('app.asar', 'app.asar.unpacked'), 'audio-route-monitor');
  audioRouteMonitor = spawn(executable, [], { stdio: ['ignore', 'pipe', 'ignore'] });
  let pending = '';
  const protect = () => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    mainWindow.webContents.setAudioMuted(true);
    mainWindow.webContents.send('audio:route-changed');
  };
  audioRouteMonitor.stdout.on('data', chunk => {
    pending += chunk.toString();
    const lines = pending.split('\n'); pending = lines.pop();
    for (const line of lines) {
      if (line === 'ready') audioGuardReady = true;
      if (line === 'changed') protect();
    }
  });
  audioRouteMonitor.on('error', () => { audioGuardReady = false; protect(); });
  audioRouteMonitor.on('exit', () => { audioGuardReady = false; protect(); });
}
app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  audioRouteMonitor?.kill();
});

function registerIpc() {
  ipcMain.handle('window:open-main', event => {
    validateAppSender(event);
    showMainWindow();
    return { ok: true };
  });
  ipcMain.handle('window:open-mini', event => {
    validateAppSender(event);
    return openMiniWindow().then(() => ({ ok: true }));
  });
  ipcMain.handle('window:mini-expanded', (event, expanded) => {
    if (!miniWindow || event.sender.id !== miniWindow.webContents.id) throw new Error('Invalid floating window');
    const bounds = miniWindow.getBounds();
    const area = screen.getDisplayMatching(bounds).workArea;
    const height = expanded ? Math.min(540, area.height) : 58;
    miniWindow.setBounds({ x: bounds.x, y: Math.max(area.y, Math.min(bounds.y, area.y + area.height - height)), width: 336, height });
  });
  ipcMain.handle('window:close-mini', event => {
    validateAppSender(event);
    miniWindow?.close();
    return { ok: true };
  });
  ipcMain.handle('quick:status', event => {
    validateMainSender(event);
    return { shortcut: globalShortcut.isRegistered('CommandOrControl+Shift+K'), audioGuard: audioGuardReady };
  });
  ipcMain.handle('audio:resume', event => {
    validateMainSender(event);
    mainWindow.webContents.setAudioMuted(false);
  });
  ipcMain.handle('background:get-settings', (event) => {
    validateMainSender(event);
    const settings = loadBackgroundSettings();
    const login = process.platform === 'darwin' ? app.getLoginItemSettings() : {};
    return { ...settings, open_at_login: Boolean(login.openAtLogin) };
  });
  ipcMain.handle('background:save-settings', (event, supplied) => {
    validateMainSender(event);
    return saveBackgroundSettings(supplied && typeof supplied === 'object' ? supplied : {});
  });
  ipcMain.handle('douyin:login', (event) => {
    validateMainSender(event);
    createLoginWindow();
    return { opened: true };
  });
  ipcMain.handle('douyin:status', async (event) => {
    validateMainSender(event);
    const connected = hasLoginCookie(await douyinCookies());
    return { connected, canSend: connected && securityStatus().complete, security: securityStatus() };
  });
  ipcMain.handle('douyin:refresh-security', async (event, roomUrl) => {
    validateMainSender(event);
    return refreshDouyinSecurity(String(roomUrl || ''));
  });
  ipcMain.handle('douyin:send-hidden', (event, roomUrl, content) => {
    validateMainSender(event);
    const operation = senderQueue.then(() => sendDouyinChatHidden(String(roomUrl || ''), String(content || '')));
    senderQueue = operation.catch(() => {});
    return operation;
  });
  ipcMain.handle('douyin:import-cookie', async (event, rawCookie) => {
    validateMainSender(event);
    return importDouyinCookie(String(rawCookie || ''));
  });
  ipcMain.handle('douyin:logout', async (event) => {
    validateMainSender(event);
    return logoutDouyin();
  });
  ipcMain.handle('dialog:output-directory', async (event) => {
    validateMainSender(event);
    const result = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory', 'createDirectory'] });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle('shell:open-external', async (event, rawUrl) => {
    validateMainSender(event);
    const url = new URL(String(rawUrl || ''));
    if (url.protocol !== 'https:') throw new Error('Only HTTPS links are allowed');
    await shell.openExternal(url.toString());
    return { ok: true };
  });
  ipcMain.handle('window:compact-mode', (event, enabled) => {
    validateMainSender(event);
    if (!mainWindow) throw new Error('Main window is not ready');
    const compact = Boolean(enabled);
    if (compact) {
      if (!normalWindowBounds) normalWindowBounds = mainWindow.getBounds();
      const saved = loadWindowState().compact || {};
      mainWindow.setMinimumSize(390, 560);
      mainWindow.setAlwaysOnTop(true, 'floating');
      mainWindow.setBounds(compactBounds(saved, normalWindowBounds), false);
      compactMode = true;
    } else {
      compactMode = false;
      mainWindow.setAlwaysOnTop(false);
      mainWindow.setMinimumSize(940, 680);
      if (normalWindowBounds) mainWindow.setBounds(normalWindowBounds, true);
      normalWindowBounds = null;
    }
    return { compact, alwaysOnTop: mainWindow.isAlwaysOnTop() };
  });
}

async function createMainWindow() {
  const launchHidden = shouldLaunchHidden();
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 940,
    minHeight: 680,
    title: 'Live Studio',
    backgroundColor: '#0b0d11',
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true
    }
  });
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  mainWindow.on('move', saveCompactWindowBounds);
  mainWindow.on('resize', saveCompactWindowBounds);
  mainWindow.on('show', () => { if (process.platform === 'darwin') app.dock.show(); });
  mainWindow.on('hide', () => { if (process.platform === 'darwin' && loadBackgroundSettings().hide_dock_when_background) app.dock.hide(); });
  mainWindow.on('close', (event) => {
    if (process.platform !== 'darwin' || quitting) return;
    event.preventDefault();
    hideMainWindow();
    const windowState = loadWindowState();
    if (windowState.backgroundCloseHintShown) return;
    saveWindowState({ backgroundCloseHintShown: true });
    dialog.showMessageBox({
      type: 'info',
      title: 'Live Studio is running in the background',
      message: 'The window is hidden and active tasks will continue',
      detail: 'Recording, live audio, and monitoring continue in the background. Use the menu bar icon to reopen the app, or press ⌘Q to quit completely.',
      buttons: ['OK'],
      defaultId: 0,
      noLink: true
    }).catch((error) => console.error(error));
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (url !== backendUrl) event.preventDefault();
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  await mainWindow.loadURL(backendUrl);
  if (!launchHidden) mainWindow.show();
  else if (process.platform === 'darwin' && loadBackgroundSettings().hide_dock_when_background) app.dock.hide();
  return mainWindow;
}

const lock = app.requestSingleInstanceLock();
if (!lock) app.quit();
else {
  app.on('second-instance', () => {
    showMainWindow();
  });
  app.whenReady().then(async () => {
    registerIpc();
    try {
      applyLoginItemSettings(loadBackgroundSettings());
      await startBackend();
      await createMainWindow();
      globalShortcut.register('CommandOrControl+Shift+K', () => {
        showMainWindow();
        mainWindow?.webContents.send('quick:open');
      });
      startAudioRouteMonitor();
      await syncDouyinSession();
      createTray();
      ensureAutomaticRecording().catch((error) => {
        console.error(`Automatic recording failed: ${error.message}`);
        if (loadBackgroundSettings().notify_errors) showSystemNotification('Automatic recording failed', error.message);
      });
    } catch (error) {
      console.error(error);
      dialog.showErrorBox('Live Studio failed to start', error.message);
      app.quit();
    }
    powerMonitor.on('resume', () => {
      setTimeout(() => {
        ensureAutomaticRecording().catch((error) => {
          console.error(`Recording recovery after wake failed: ${error.message}`);
          if (loadBackgroundSettings().notify_errors) showSystemNotification('Recording recovery after wake failed', error.message);
        });
        refreshTray().catch(() => {});
      }, 2500);
    });
    app.on('activate', () => {
      if (!mainWindow) createMainWindow();
      else showMainWindow();
    });
  });
}

app.on('before-quit', (event) => {
  if (quitting) {
    if (backend && !backend.killed) backend.kill(process.platform === 'win32' ? undefined : 'SIGINT');
    return;
  }
  event.preventDefault();
  if (quitCheckInProgress) return;
  quitCheckInProgress = true;
  (async () => {
    let recording = false;
    try {
      if (backendUrl) {
        const origin = new URL(backendUrl).origin;
        const response = await fetch(`${origin}/api/state`, {
          headers: { 'X-LiveRecorder-Token': backendToken }
        });
        if (response.ok) recording = Boolean((await response.json()).status?.running);
      }
    } catch {}
    if (recording) {
      const options = {
        type: 'warning',
        title: 'Live recording in progress',
        message: 'Recording must stop and save before quitting',
        detail: 'Finalizing may take a few seconds. The app will quit automatically afterward.',
        buttons: ['Stop, Save & Quit', 'Keep Running'],
        defaultId: 1,
        cancelId: 1,
        noLink: true
      };
      const result = mainWindow
        ? await dialog.showMessageBox(mainWindow, options)
        : await dialog.showMessageBox(options);
      if (result.response !== 0) {
        quitCheckInProgress = false;
        return;
      }
      try {
        await postBackend('/api/stop', {});
      } catch (error) {
        dialog.showErrorBox('Unable to stop safely', `${error.message}\n\nStop the recording from the main window, then quit again.`);
        quitCheckInProgress = false;
        return;
      }
    }
    quitting = true;
    if (trayRefreshTimer) clearInterval(trayRefreshTimer);
    if (powerBlockerId != null && powerSaveBlocker.isStarted(powerBlockerId)) powerSaveBlocker.stop(powerBlockerId);
    app.quit();
  })().catch((error) => {
    console.error(error);
    quitCheckInProgress = false;
  });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
