// Offline visual review. Uses fixture data; never connects to the running recorder.
const { app, BrowserWindow } = require('electron');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const output = path.resolve(__dirname, '../output/ui-review');
const now = Math.floor(Date.now() / 1000);
const anchors = ['小婷winko', 'hillusion', '叫我小榕', '一个用于检查长昵称是否溢出的主播名字', '许枝'].map((name, i) => ({ id: String(i), name, live_url: `https://live.douyin.com/${i}`, profile_url: `https://www.douyin.com/user/${i}`, enabled_recording: i !== 2, last_live_status: i < 3 ? 'live' : i === 3 ? 'error' : 'offline', last_resolved_at: now - (i === 4 ? 86400 : 20) }));
const state = { anchors, settings: {}, status: { running: true, room_states: { 0: { state: 'recording' } } }, storage: {}, baidupan: {}, update: {}, interaction: {}, work_pull: {}, recordings: [], recording_groups: [], gifts: {} };
const mediaFiles = [0,1,2].map(i=>({path:`/preview/recording_${i}.mp4`,name:i===1?'小婷winko_2026-11-26_完整录像_用很长的文件名称检查小窗口下是否正确省略.mp4':`小婷winko_2026-11-26_00${i}.mp4`,modified:now,size:3*1024**3,kind:'video',source:'recording',integrity:{status:i===1?'warning':'healthy',duration_seconds:3600,warning:i===1?'部分分段时间戳存在跳变，建议播放确认。':''},upload_status:i===2?'paused':'success'}));
const library = {total_files:3,total_anchors:1,total_size:9*1024**3,anchors:[{anchor:'小婷winko',folder:'/preview',total_files:3,total_size:9*1024**3,video_count:3,audio_count:0,files:mediaFiles,recording_sessions:[]}]};
state.baidupan={config:{enabled:true,auto_upload:true,delete_after_upload:true,keep_local_days:1,max_concurrent_uploads:3},auth:{status:'authorized'},queue:[{id:'preview',record_name:'小婷winko',status:'success',file_size:3*1024**3,remote_dir:'/apps/LiveRecorder/小婷winko'}]};
mediaFiles[0].archive_detail={upload_evidence:'task',cleanup_due_at:now+3600,remote_checked_at:now-600};
mediaFiles[1].archive_detail={upload_evidence:'history'};
mediaFiles[2].archive_detail={upload_evidence:'task'};
library.anchors[0].recording_sessions=[{id:'session-preview',anchor:anchors[0].name,started_at:now,segment_count:2,total_size:9*1024**3,format:'MP4',settled:true,merged_file:mediaFiles[0],files:mediaFiles}];
let failAction = false;
const server = http.createServer((req, res) => {
  if (req.url === '/seed') { res.setHeader('Content-Type', 'text/html'); res.end('<!doctype html><title>Offline UI preview</title>'); }
  else if (req.url.startsWith('/api/')) { res.setHeader('Content-Type', 'application/json'); if (failAction && req.method === 'POST') { res.statusCode = 400; res.end(JSON.stringify({error:'测试：状态检查失败，请重试'})); } else res.end(JSON.stringify(req.url.startsWith('/api/state') ? state : req.url.startsWith('/api/media-library') ? {library,upload_reconciliation:{files:[],counts:{}}} : { lines: [], events: [], jobs:[], cursor: 0 })); }
  else { res.setHeader('Content-Type', 'text/html'); res.end(fs.readFileSync(path.resolve(__dirname, '../desktop/ui-dist/index.html'))); }
});
const errors = [];
app.whenReady().then(async () => {
  fs.mkdirSync(output, { recursive: true });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  const win = new BrowserWindow({ width: 1280, height: 900, show: false, webPreferences: { contextIsolation: true, nodeIntegration: false } });
  // Fixture resets navigate without a real mouse gesture. Chromium suppresses the
  // native beforeunload prompt in that case; explicit in-app guards are tested below.
  win.webContents.on('console-message', event => { if ((event.level === 'error' || event.level === 3) && !event.message.includes('Failed to load resource') && !event.message.startsWith("Blocked attempt to show a 'beforeunload' confirmation panel")) errors.push(event.message); });
  const settle = () => new Promise(resolve => setTimeout(resolve, 350));
  async function shot(name, page, width = 1280, height = 900, mini = false, theme = 'dark', modes = {}) {
    win.setContentSize(width, height);
    await win.loadURL(url + '/seed');
    await win.webContents.executeJavaScript(`localStorage.setItem('liveRecorderLanguage','zh');localStorage.setItem('liveRecorderLastView',${JSON.stringify(page)});localStorage.setItem('liveRecorderTheme',${JSON.stringify(theme)});localStorage.setItem('liveRecorderSelectedAnchor','0');localStorage.setItem('liveRecorderCompactMode',${JSON.stringify(modes.compact?'1':'0')});localStorage.setItem('liveRecorderWorkMode',${JSON.stringify(modes.work?'1':'0')});`);
    await win.loadURL(url + (mini ? '/?mini=1' : '/'));
    let ready = false;
    for (let attempt=0; attempt<40; attempt++) {
      ready = await win.webContents.executeJavaScript(mini ? `!!document.querySelector('.miniBar') && !document.body.textContent.includes('正在连接…')` : `!!document.querySelector('.workspace') && !document.querySelector('[aria-busy="true"]')`);
      if (ready) break;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    if (!ready) throw new Error(name + ': UI did not finish loading');
    await win.webContents.executeJavaScript(`document.fonts.ready.then(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))`);
    await settle();
    if (mini) { await win.webContents.executeJavaScript(`document.querySelector('.miniPrimary').click()`); await settle(); }
    await fs.promises.writeFile(path.join(output, `${name}.png`), (await win.webContents.capturePage()).toPNG());
    const overflow = await win.webContents.executeJavaScript(`({width:innerWidth,scroll:document.documentElement.scrollWidth,heading:document.querySelector('h3')?.textContent,selected:document.querySelector('.miniAnchor.selected')?.textContent})`);
    console.log(name, JSON.stringify(overflow));
    if (overflow.scroll > overflow.width) throw new Error(name + ': horizontal overflow');
    const clipped = await win.webContents.executeJavaScript(`Array.from(document.querySelectorAll('.panelBody,.roomCard,.workspaceActions')).filter(el=>el.scrollWidth > el.clientWidth + 2).map(el=>({className:el.className,client:el.clientWidth,scroll:el.scrollWidth}))`);
    if (clipped.length) throw new Error(name + ': clipped content ' + JSON.stringify(clipped));
    if (!mini) {
      const contrast = await win.webContents.executeJavaScript(`(()=>{const probe=document.createElement('span');probe.style.color='var(--mantine-color-dimmed)';probe.style.backgroundColor='var(--panel)';document.body.append(probe);const style=getComputedStyle(probe);const luminance=color=>{const values=color.match(/[\\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});return values[0]*.2126+values[1]*.7152+values[2]*.0722};const a=luminance(style.color),b=luminance(style.backgroundColor);probe.remove();return(Math.max(a,b)+.05)/(Math.min(a,b)+.05)})()`);
      if (contrast < 4.5) throw new Error(name + ': muted text contrast too low ' + contrast.toFixed(2));
    }
  }
  let failed = false;
  try {
    await shot('dashboard', 'record');
    await shot('interaction', 'interact');
    await win.webContents.executeJavaScript(`document.querySelector('.anchorPicker input').click()`);
    await settle();
    if (!await win.webContents.executeJavaScript(`Array.from(document.querySelectorAll('[role=option]')).some(el=>el.textContent.includes('录制中'))`)) throw new Error('Anchor options did not expose presence');
    await win.webContents.executeJavaScript(`localStorage.setItem('liveRecorderSelectedAnchor','1')`);
    await win.loadURL(url);
    await settle();
    if (!await win.webContents.executeJavaScript(`document.querySelector('.anchorPicker input')?.value === 'hillusion'`)) throw new Error('Saved anchor selection was lost during startup');
    await shot('selection-context','interact');
    state.interaction={listening:true,room_url:anchors[1].live_url};
    await new Promise(resolve=>setTimeout(resolve,4500));
    if (!await win.webContents.executeJavaScript(`document.querySelector('.workspaceContext')?.textContent.includes('当前选择：小婷winko') && document.querySelector('.workspaceContext')?.textContent.includes('监听：hillusion')`)) throw new Error('Selected and listening anchor context is ambiguous');
    await fs.promises.writeFile(path.join(output,'selection-context.png'),(await win.webContents.capturePage()).toPNG());
    state.interaction={};
    await shot('anchors', 'anchors');
    if (!await win.webContents.executeJavaScript(`document.querySelector('h3')?.textContent==='主播库' && !document.querySelector('.mantine-Drawer-content')`)) throw new Error('Anchor library is not the primary view');
    await win.webContents.executeJavaScript(`(()=>{const input=document.querySelector('.fieldGrid input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'未保存的昵称');input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    await settle();
    await win.webContents.executeJavaScript(`window.confirm=()=>false;document.querySelectorAll('.anchorItem')[1].click();document.querySelector('.sidebar nav button').click()`);
    await settle();
    if (!await win.webContents.executeJavaScript(`document.querySelector('.fieldGrid input')?.value==='未保存的昵称' && document.querySelector('.anchorItem.active')?.textContent.includes('小婷winko')`)) throw new Error('Unsaved anchor changes were lost');
    await shot('anchors', 'anchors');
    await win.webContents.executeJavaScript(`Array.from(document.querySelectorAll('button')).find(el=>el.textContent==='添加主播').click()`);
    await settle();
    if (!await win.webContents.executeJavaScript(`document.querySelector('.mantine-Drawer-content')?.textContent.includes('粘贴手机分享')`)) throw new Error('Add anchor workflow is missing');
    await fs.promises.writeFile(path.join(output,'anchors-add.png'),(await win.webContents.capturePage()).toPNG());
    await shot('works', 'works');
    await win.webContents.executeJavaScript(`Array.from(document.querySelectorAll('button')).find(el=>el.textContent==='开始拉取作品').click()`);
    await settle();
    if (!await win.webContents.executeJavaScript(`Array.from(document.querySelectorAll('button')).some(el=>el.textContent==='任务已提交'&&el.disabled)`)) throw new Error('Work submission did not prevent duplicate clicks');
    await shot('works-narrow', 'works', 390, 760);
    await shot('library', 'library');
    if (!await win.webContents.executeJavaScript(`!!document.querySelector('.sessionCard') && !document.querySelector('.sessionFiles').open`)) throw new Error('Sessions must be primary and raw segments collapsed');
    await win.webContents.executeJavaScript(`Array.from(document.querySelectorAll('button')).find(el=>el.textContent==='场次详情').click()`);
    await settle();
    if (!await win.webContents.executeJavaScript(`document.querySelector('.mantine-Drawer-content')?.textContent.includes('文件已复核')`)) throw new Error('Session archive evidence differs from file evidence');
    await shot('library', 'library');
    if (!await win.webContents.executeJavaScript(`document.querySelector('.mediaCards')?.textContent.includes('曾上传，待复核') && document.querySelector('.mediaCards')?.textContent.includes('保留至')`)) throw new Error('Local and cloud archive states are not distinct');
    await win.webContents.executeJavaScript(`(()=>{const input=document.querySelector('input[aria-label="搜索文件名"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'不存在的录像');input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    await settle();
    if (!await win.webContents.executeJavaScript(`document.querySelector('.mediaCards')?.textContent.includes('没有匹配文件') && !document.querySelector('.mediaFileCard')`)) throw new Error('Media file search did not filter the list');
    await shot('library-narrow', 'library', 390, 760);
    await shot('settings', 'settings');
    await win.webContents.executeJavaScript(`(()=>{const input=document.querySelector('.fieldGrid input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'/preview/new-output');input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    await settle();
    if (!await win.webContents.executeJavaScript(`document.body.textContent.includes('有未保存修改') && Array.from(document.querySelectorAll('button')).some(el=>el.textContent.includes('保存设置')&&!el.disabled)`)) throw new Error('Settings dirty state was not visible');
    if (!await win.webContents.executeJavaScript(`!!document.querySelector('.settingsSaveBar')`)) throw new Error('Persistent settings save bar missing');
    await win.webContents.executeJavaScript(`window.confirm=()=>false;document.querySelector('.sidebar nav button').click()`);
    await settle();
    if (!await win.webContents.executeJavaScript(`!!document.querySelector('.settingsSaveBar') && document.querySelector('.sidebar nav button.active')?.textContent.includes('设置')`)) throw new Error('Unsaved settings were lost on navigation');
    await fs.promises.writeFile(path.join(output,'settings-dirty.png'),(await win.webContents.capturePage()).toPNG());
    await shot('settings-narrow', 'settings', 390, 760);
    await shot('light', 'interact', 1280, 900, false, 'white');
    for (const theme of ['mist','sand','midnight','forest','wine']) await shot(`theme-${theme}`, 'record', 1280, 900, false, theme);
    await shot('transcripts', 'transcripts');
    await shot('compact-mode', 'interact', 460, 760, false, 'dark', {compact:true});
    await shot('work-mode', 'interact', 1280, 900, false, 'dark', {work:true});
    await shot('compact', 'interact', 460, 760);
    await shot('narrow', 'record', 390, 760);
    await shot('mini', 'record', 336, 540, true);
    const before = await win.webContents.executeJavaScript(`document.querySelector('.miniAnchor').getBoundingClientRect().height`);
    await win.webContents.executeJavaScript(`document.querySelectorAll('.miniAnchorSelect')[1].click()`);
    await settle();
    const after = await win.webContents.executeJavaScript(`document.querySelector('.miniAnchor').getBoundingClientRect().height`);
    if (before!==after || !await win.webContents.executeJavaScript(`document.querySelector('.miniSelectedActions').textContent.includes('叫我小榕')`)) throw new Error('Floating selection moved the list or did not update actions');
    await win.webContents.executeJavaScript(`document.querySelector('.miniAnchorSelect').click()`);
    await settle();
    failAction = true;
    await win.webContents.executeJavaScript(`Array.from(document.querySelectorAll('.miniSelectedActions button')).find(el=>el.textContent==='检查状态').click()`);
    await new Promise(resolve=>setTimeout(resolve, 2800));
    if (!await win.webContents.executeJavaScript(`document.querySelector('.miniMessage.failed')?.textContent.includes('状态检查失败')`)) throw new Error('Polling cleared the operation error');
    failAction = false;
    await win.webContents.executeJavaScript(`(()=>{const input=document.querySelector('input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'不存在的主播');input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    await settle();
    if (!await win.webContents.executeJavaScript(`document.querySelector('.miniEmpty')?.textContent.includes('没有匹配')`)) throw new Error('Search empty state failed');
    await win.webContents.executeJavaScript(`document.querySelector('.miniEmpty button').click()`);
    await settle();
    if (!await win.webContents.executeJavaScript(`!!document.querySelector('.miniAnchor')`)) throw new Error('Clearing search failed');
    await win.webContents.executeJavaScript(`document.querySelector('.miniAnchorSelect').click();document.querySelector('.miniShell').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));`);
    await settle();
    if (await win.webContents.executeJavaScript(`!!document.querySelector('.miniPanel')`)) throw new Error('Escape did not collapse floating controls');
    await shot('quick', 'record');
    await win.webContents.executeJavaScript(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('快捷操作')).click()`);
    await settle();
    await fs.promises.writeFile(path.join(output, 'quick.png'), (await win.webContents.capturePage()).toPNG());
    state.anchors = [];
    await shot('empty', 'record', 940, 760);
    console.log('renderErrors', JSON.stringify(errors));
    if (errors.length) throw new Error('Renderer errors detected');
  } catch(error) { failed=true; throw error; }
  finally { win.destroy(); server.close(); if (!failed) app.quit(); }
}).catch(error => { console.error(error); app.exit(1); });
