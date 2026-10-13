const { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, Notification, powerMonitor, powerSaveBlocker, screen, session, shell, Tray } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { LOGIN_COOKIE_NAMES, parseCookieHeader } = require('./douyin-cookie.cjs');

const DOUYIN_PARTITION = 'persist:douyin-auth';
const DOUYIN_LOGIN_URL = 'https://www.douyin.com/';

app.setName('播录助手');

let mainWindow = null;
let loginWindow = null;
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
    for (const [name, room] of Object.entries(rooms)) {
      const before = notificationSnapshot.rooms[name];
      if (room.state === 'recording' && before !== 'recording') {
        showSystemNotification('主播已开播，开始录制', `${name}${room.path ? `\n${path.basename(room.path)}` : ''}`);
      } else if (before === 'recording' && room.state !== 'recording') {
        showSystemNotification('直播录制已结束', `${name}的录像已经保存并进入后续处理。`);
      }
    }
  }
  for (const item of queue) {
    const before = notificationSnapshot.uploads[item.id];
    if (!before || before === item.status) continue;
    const name = item.record_name || path.basename(item.save_file_path || '') || '录像文件';
    if (item.status === 'success' && settings.notify_upload) {
      showSystemNotification('百度网盘归档完成', `${name}已成功上传。`);
    } else if (item.status === 'failed' && settings.notify_errors) {
      showSystemNotification('百度网盘上传失败', `${name}上传失败，可在上传队列中重试。`);
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
    backend.on('error', (error) => fail(`无法启动 Python 录制引擎：${error.message}`));
    backend.on('exit', (code) => {
      if (!quitting) fail(`录制引擎意外退出（${code ?? 'unknown'}）`);
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
    timeout = setTimeout(() => fail('内置录制引擎启动超时，请重新启动应用'), 45000);
  });
}

async function postBackend(pathname, body) {
  if (!backendUrl) throw new Error('录制引擎尚未就绪');
  const origin = new URL(backendUrl).origin;
  const response = await fetch(`${origin}${pathname}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-LiveRecorder-Token': backendToken },
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error((await response.json()).error || '本地服务请求失败');
  return response.json();
}

async function backendState() {
  if (!backendUrl) throw new Error('录制引擎尚未就绪');
  const origin = new URL(backendUrl).origin;
  const response = await fetch(`${origin}/api/state`, {
    headers: { 'X-LiveRecorder-Token': backendToken }
  });
  if (!response.ok) throw new Error((await response.json()).error || '无法读取本地服务状态');
  return response.json();
}

async function ensureAutomaticRecording() {
  const settings = loadBackgroundSettings();
  if (!settings.auto_start_recording) return false;
  const state = await backendState();
  if (state.status?.running) return true;
  if (!(state.rooms || []).some((room) => room.active)) throw new Error('自动录制已开启，但没有启用的直播间');
  await postBackend('/api/start', { settings: state.settings || {} });
  return true;
}

function showMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

async function openCompactWindow() {
  showMainWindow();
  await mainWindow.webContents.executeJavaScript('setCompactMode(true)');
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
  tray.setToolTip(recording ? `播录助手 · ${recordingRooms || '正在'}录制` : '播录助手 · 后台待机');
  if (process.platform === 'darwin') tray.setTitle(recording ? ' ●' : '');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: recording ? `● 正在录制${recordingRooms ? ` · ${recordingRooms} 个直播间` : ''}` : '○ 录制服务待机', enabled: false },
    { label: uploading ? `网盘上传中 · ${uploading} 个文件` : pending ? `网盘队列 · ${pending} 个任务` : '网盘队列空闲', enabled: false },
    { type: 'separator' },
    {
      label: recording ? '停止录制并保存' : '开始自动录制',
      click: async () => {
        try {
          if (recording) await postBackend('/api/stop', {});
          else {
            const state = await backendState();
            await postBackend('/api/start', { settings: state.settings || {} });
          }
          await refreshTray();
        } catch (error) {
          dialog.showErrorBox('录制操作失败', error.message);
        }
      }
    },
    { label: '打开小窗控制', click: () => openCompactWindow().catch((error) => dialog.showErrorBox('无法打开小窗', error.message)) },
    { label: '打开播录助手', click: showMainWindow },
    { label: '隐藏窗口', enabled: Boolean(mainWindow?.isVisible()), click: () => mainWindow?.hide() },
    { type: 'separator' },
    { label: '退出播录助手', click: () => app.quit() }
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
    title: '登录抖音账号',
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

function registerIpc() {
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
    if (url.protocol !== 'https:') throw new Error('只允许打开 HTTPS 链接');
    await shell.openExternal(url.toString());
    return { ok: true };
  });
  ipcMain.handle('window:compact-mode', (event, enabled) => {
    validateMainSender(event);
    if (!mainWindow) throw new Error('主窗口尚未就绪');
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
    title: '播录助手',
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
  mainWindow.on('close', (event) => {
    if (process.platform !== 'darwin' || quitting) return;
    event.preventDefault();
    mainWindow.hide();
    const windowState = loadWindowState();
    if (windowState.backgroundCloseHintShown) return;
    saveWindowState({ backgroundCloseHintShown: true });
    dialog.showMessageBox({
      type: 'info',
      title: '播录助手已在后台运行',
      message: '窗口已隐藏，当前任务不会中断',
      detail: '录制、直播音频和弹幕监听会继续运行。可从顶部菜单栏图标重新打开或控制录制；如需完全退出，请按 ⌘Q。',
      buttons: ['知道了'],
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
      await syncDouyinSession();
      createTray();
      ensureAutomaticRecording().catch((error) => {
        console.error(`自动开始录制失败：${error.message}`);
        if (loadBackgroundSettings().notify_errors) showSystemNotification('自动录制未能启动', error.message);
      });
    } catch (error) {
      console.error(error);
      dialog.showErrorBox('播录助手启动失败', error.message);
      app.quit();
    }
    powerMonitor.on('resume', () => {
      setTimeout(() => {
        ensureAutomaticRecording().catch((error) => {
          console.error(`唤醒后恢复录制失败：${error.message}`);
          if (loadBackgroundSettings().notify_errors) showSystemNotification('唤醒后恢复录制失败', error.message);
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
        title: '正在录制直播',
        message: '退出前需要先停止录制并保存视频',
        detail: '保存和封装可能需要几秒钟，完成后应用会自动退出。',
        buttons: ['停止录制并退出', '继续使用'],
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
        dialog.showErrorBox('无法安全停止录制', `${error.message}\n\n请在主界面停止录制后再退出。`);
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
