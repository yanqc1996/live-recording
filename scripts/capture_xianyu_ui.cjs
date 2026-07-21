const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const path = require('node:path');

const url = process.argv[2];
if (!url) {
  console.error('Usage: electron scripts/capture_xianyu_ui.cjs <url>');
  process.exit(1);
}

const outDir = path.resolve(__dirname, '..', 'release', '咸鱼上架素材包');
fs.mkdirSync(outDir, { recursive: true });

async function wait(ms) {
  await new Promise(resolve => setTimeout(resolve, ms));
}

async function capture(win, name) {
  const image = await win.capturePage();
  fs.writeFileSync(path.join(outDir, name), image.toPNG());
}

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    show: false,
    width: 1440,
    height: 980,
    webPreferences: { offscreen: true, sandbox: false, webSecurity: false }
  });
  await win.loadURL(url);
  await wait(1200);
  await capture(win, '06-真实界面-本地录制.png');
  await win.webContents.executeJavaScript("document.getElementById('tabInteract').click()");
  await wait(700);
  await capture(win, '07-真实界面-直播互动.png');
  await win.webContents.executeJavaScript("document.getElementById('tabWorks').click()");
  await wait(700);
  await capture(win, '08-真实界面-作品拉取.png');
  win.destroy();
  app.quit();
}).catch(error => {
  console.error(error);
  app.quit();
});
