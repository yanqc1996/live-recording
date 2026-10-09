const { app, BrowserWindow, dialog, ipcMain, session, shell } = require('electron');
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
let syncTimer = null;
let douyinSecurity = {};
let normalWindowBounds = null;

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
      BOLU_APP_VERSION: app.getVersion()
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
  await postBackend('/api/auth/douyin', { cookie, security: douyinSecurity });
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
  ipcMain.handle('window:compact-mode', (event, enabled) => {
    validateMainSender(event);
    if (!mainWindow) throw new Error('主窗口尚未就绪');
    const compact = Boolean(enabled);
    if (compact) {
      if (!normalWindowBounds) normalWindowBounds = mainWindow.getBounds();
      mainWindow.setMinimumSize(390, 560);
      mainWindow.setAlwaysOnTop(true, 'floating');
      mainWindow.setBounds({
        x: normalWindowBounds.x + Math.max(0, normalWindowBounds.width - 430),
        y: normalWindowBounds.y,
        width: 430,
        height: 720
      }, true);
    } else {
      mainWindow.setAlwaysOnTop(false);
      mainWindow.setMinimumSize(940, 680);
      if (normalWindowBounds) mainWindow.setBounds(normalWindowBounds, true);
      normalWindowBounds = null;
    }
    return { compact, alwaysOnTop: mainWindow.isAlwaysOnTop() };
  });
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 940,
    minHeight: 680,
    title: '播录助手',
    backgroundColor: '#0b0d11',
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
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (url !== backendUrl) event.preventDefault();
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  return mainWindow.loadURL(backendUrl);
}

const lock = app.requestSingleInstanceLock();
if (!lock) app.quit();
else {
  app.on('second-instance', () => {
    if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus(); }
  });
  app.whenReady().then(async () => {
    registerIpc();
    try {
      await startBackend();
      await createMainWindow();
      await syncDouyinSession();
    } catch (error) {
      console.error(error);
      dialog.showErrorBox('播录助手启动失败', error.message);
      app.quit();
    }
    app.on('activate', () => { if (!mainWindow) createMainWindow(); });
  });
}

app.on('before-quit', () => {
  quitting = true;
  if (backend && !backend.killed) backend.kill(process.platform === 'win32' ? undefined : 'SIGINT');
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
