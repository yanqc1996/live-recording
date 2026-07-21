const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const outDir = path.join(root, 'release', '咸鱼上架素材包');
fs.mkdirSync(outDir, { recursive: true });
const tempDir = path.join(root, 'release', 'xianyu-html-temp');
fs.rmSync(tempDir, { recursive: true, force: true });
fs.mkdirSync(tempDir, { recursive: true });

const iconPath = path.join(root, 'assets', 'app-icon.png');
const iconData = fs.existsSync(iconPath) ? `file://${iconPath}` : '';

const baseStyle = `
  :root{--bg:#071018;--panel:#111827;--panel2:#0d1421;--line:#26344b;--muted:#98a6b8;--text:#f7fbff;--blue:#6fb8ff;--pink:#ff4b79;--green:#49d391;--gold:#ffd37a}
  *{box-sizing:border-box} body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:radial-gradient(circle at 14% 6%,#1b3761 0,transparent 32%),linear-gradient(145deg,#08111f,#05070c);color:var(--text)}
  .canvas{width:1242px;height:1660px;padding:76px;position:relative;overflow:hidden}
  .orb{position:absolute;border-radius:999px;filter:blur(0);opacity:.16}.orb.a{width:360px;height:360px;background:#6fb8ff;right:-80px;top:120px}.orb.b{width:280px;height:280px;background:#ff4b79;left:-80px;bottom:160px}
  .top{display:flex;align-items:center;gap:28px}.icon{width:132px;height:132px;border-radius:32px;box-shadow:0 28px 70px #0009}.brand h1{font-size:58px;line-height:1;margin:0 0 12px}.brand p{font-size:25px;color:var(--muted);margin:0}
  .badge{display:inline-flex;align-items:center;gap:10px;border:1px solid #39506d;background:#ffffff0d;border-radius:999px;padding:12px 20px;color:#dbeafe;font-size:22px}
  .hero{margin-top:72px}.headline{font-size:82px;line-height:1.08;font-weight:850;letter-spacing:-2px;margin:0}.headline span{background:linear-gradient(90deg,#89d2ff,#ff7ba1);-webkit-background-clip:text;color:transparent}
  .sub{font-size:30px;line-height:1.55;color:#c7d3e2;margin:30px 0 0;max-width:920px}
  .panel{background:linear-gradient(180deg,#121b2a,#0c121d);border:1px solid var(--line);border-radius:34px;box-shadow:0 30px 90px #0008;overflow:hidden}
  .panel-head{height:76px;border-bottom:1px solid var(--line);display:flex;align-items:center;padding:0 30px;gap:14px}.dot{width:14px;height:14px;border-radius:50%;background:#ff5f57}.dot.y{background:#ffbd2e}.dot.g{background:#28c840}.title{margin-left:12px;color:#cbd7e8;font-size:22px}
  .mock{margin-top:58px;padding:28px}.tabs{display:flex;gap:12px;margin-bottom:24px}.tab{padding:14px 20px;border-radius:16px;background:#1a2535;color:#9fb0c6;font-size:20px}.tab.on{background:#eaf2ff;color:#111827;font-weight:700}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.card{background:#0b111b;border:1px solid #223047;border-radius:24px;padding:24px}.card h3{font-size:25px;margin:0 0 12px}.card p{font-size:19px;color:#9fb0c6;line-height:1.5;margin:0}.stat{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:20px}.stat div{background:#121c2b;border:1px solid #25364f;border-radius:20px;padding:18px}.stat b{font-size:36px;display:block}.stat span{font-size:17px;color:#99a8bb}
  .features{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:56px}.feature{background:#ffffff0b;border:1px solid #30415b;border-radius:28px;padding:28px}.feature b{font-size:28px;display:block;margin-bottom:10px}.feature p{font-size:21px;color:#b9c6d8;line-height:1.45;margin:0}
  .price{margin-top:56px;background:linear-gradient(120deg,#eaf2ff,#ffe9f0);color:#101827;border-radius:34px;padding:34px 40px;display:flex;align-items:center;justify-content:space-between}.price .n{font-size:72px;font-weight:900}.price .n small{font-size:28px}.price .copy{font-size:24px;line-height:1.45;color:#1f2937}
  .foot{position:absolute;left:76px;right:76px;bottom:54px;color:#8ea0b8;font-size:20px;line-height:1.5}
  .list{display:grid;gap:18px}.row{display:flex;align-items:center;gap:18px;background:#0b111b;border:1px solid #223047;border-radius:24px;padding:24px}.num{width:52px;height:52px;border-radius:18px;background:#eaf2ff;color:#0d1421;font-size:25px;font-weight:900;display:grid;place-items:center}.row b{font-size:28px}.row p{font-size:20px;color:#a9b7ca;margin:6px 0 0}
  .warning{margin-top:34px;background:#fff4cc12;border:1px solid #ffd37a55;border-radius:24px;padding:24px;color:#ffe5a3;font-size:21px;line-height:1.55}
`;

function shell(content) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>${baseStyle}</style></head><body>${content}</body></html>`;
}

const pages = [
  {
    name: '01-闲鱼首图-播录助手.png',
    html: shell(`
      <div class="canvas">
        <div class="orb a"></div><div class="orb b"></div>
        <div class="top"><img class="icon" src="${iconData}"><div class="brand"><h1>播录助手</h1><p>Mac 本地直播录制 · 弹幕观察 · 素材归档</p></div></div>
        <div class="hero">
          <div class="badge">买断授权 · 本地运行 · 无需安装 Python</div>
          <h2 class="headline">给主播素材<br><span>一个本地工作台</span></h2>
          <p class="sub">直播录制、弹幕监听、只听音频、作品拉取、主播媒体库，一套桌面软件统一管理。适合内容剪辑、直播复盘、素材归档和轻量运营观察。</p>
        </div>
        <div class="features">
          <div class="feature"><b>本地录制</b><p>直播源保存到本机，支持画质、格式、分段、转 MP4 等设置。</p></div>
          <div class="feature"><b>直播互动</b><p>弹幕/用户信息监听，支持工作模式和礼物贡献榜展示。</p></div>
          <div class="feature"><b>作品拉取</b><p>按用户主页拉取作品，按作品 ID 和时间做去重。</p></div>
          <div class="feature"><b>主播媒体库</b><p>按主播聚合录制、作品、音频和本地素材。</p></div>
        </div>
        <div class="price"><div><div class="n">¥99<small> 起</small></div></div><div class="copy">建议上架价：99-199<br>买断授权｜一机一码｜含安装指导</div></div>
        <div class="foot">注：本工具仅用于个人本地素材管理，请自行确认内容授权与平台规则。</div>
      </div>`)
  },
  {
    name: '02-功能总览.png',
    html: shell(`
      <div class="canvas">
        <div class="top"><img class="icon" src="${iconData}"><div class="brand"><h1>五大功能区</h1><p>不是脚本，是完整桌面工作台</p></div></div>
        <div class="mock panel">
          <div class="panel-head"><span class="dot"></span><span class="dot y"></span><span class="dot g"></span><span class="title">播录助手 / 功能总览</span></div>
          <div class="mock">
            <div class="tabs"><div class="tab on">主播库</div><div class="tab">本地录制</div><div class="tab">直播互动</div><div class="tab">作品拉取</div><div class="tab">媒体库</div></div>
            <div class="grid">
              <div class="card"><h3>主播库统一入口</h3><p>配置主播主页或直播间地址，统一用于录制、互动、作品拉取和媒体管理。</p></div>
              <div class="card"><h3>开播巡检</h3><p>可手动或定时巡检主播状态，减少反复打开网页查看的麻烦。</p></div>
              <div class="card"><h3>本地录制</h3><p>支持画质选择、格式选择、分段录制、录后转 MP4、本地目录管理。</p></div>
              <div class="card"><h3>媒体资产管理</h3><p>按主播聚合本地文件，查看视频/音频/作品数量和体积。</p></div>
            </div>
            <div class="stat"><div><b>5</b><span>功能区</span></div><div><b>0</b><span>用户环境依赖</span></div><div><b>1</b><span>本地授权码</span></div></div>
          </div>
        </div>
        <div class="warning">卖点表达建议：强调“本地工具 / 素材管理 / 直播复盘”，不要承诺第三方平台接口永久稳定。</div>
      </div>`)
  },
  {
    name: '03-授权安装流程.png',
    html: shell(`
      <div class="canvas">
        <div class="top"><img class="icon" src="${iconData}"><div class="brand"><h1>买断授权流程</h1><p>一机一码，适合闲鱼交付</p></div></div>
        <div class="list" style="margin-top:68px">
          <div class="row"><div class="num">1</div><div><b>用户安装 DMG</b><p>拖入应用程序，首次打开按引导右键打开。</p></div></div>
          <div class="row"><div class="num">2</div><div><b>复制当前设备码</b><p>软件首页展示设备码，用户复制后发给卖家。</p></div></div>
          <div class="row"><div class="num">3</div><div><b>卖家生成授权码</b><p>基于设备码、昵称、订单号生成专属买断码。</p></div></div>
          <div class="row"><div class="num">4</div><div><b>用户粘贴激活</b><p>激活成功后录制、互动、作品拉取等功能自动解锁。</p></div></div>
        </div>
        <div class="mock panel">
          <div class="panel-head"><span class="dot"></span><span class="dot y"></span><span class="dot g"></span><span class="title">软件授权</span></div>
          <div class="mock">
            <div class="card"><h3>当前设备码</h3><p style="font-family:ui-monospace;font-size:28px;color:#eaf2ff">2980-8709-BCFE-2F1D</p></div>
            <div class="card" style="margin-top:18px"><h3>授权状态</h3><p style="color:#49d391">买断授权已激活</p></div>
          </div>
        </div>
        <div class="foot">交付建议：不要把生成授权码脚本发给买家，只发送 DMG、启动引导和授权码。</div>
      </div>`)
  },
  {
    name: '04-本地录制与互动.png',
    html: shell(`
      <div class="canvas">
        <div class="top"><img class="icon" src="${iconData}"><div class="brand"><h1>录制 + 互动</h1><p>上班挂着也不刺眼的工作模式</p></div></div>
        <div class="mock panel">
          <div class="panel-head"><span class="dot"></span><span class="dot y"></span><span class="dot g"></span><span class="title">本地录制 / 直播互动</span></div>
          <div class="mock">
            <div class="tabs"><div class="tab on">本地录制</div><div class="tab">直播互动</div><div class="tab">只听音频</div><div class="tab">礼物贡献榜</div></div>
            <div class="grid">
              <div class="card"><h3>录制保存到本机</h3><p>默认不上传，用户可选择保存目录、格式、画质和分段策略。</p></div>
              <div class="card"><h3>弹幕监听</h3><p>查看实时弹幕和用户信息，工作模式弱化无关提示，保留核心弹幕。</p></div>
              <div class="card"><h3>只听音频</h3><p>不方便看视频时，只获取音频源进行监听，内置自动重连。</p></div>
              <div class="card"><h3>礼物贡献榜</h3><p>从直播间榜单接口展示贡献数据，不做本地估算。</p></div>
            </div>
          </div>
        </div>
        <div class="features">
          <div class="feature"><b>适合剪辑复盘</b><p>录完后本地管理，方便后续剪素材。</p></div>
          <div class="feature"><b>适合轻量观察</b><p>不用网页窗口一直开着盯，工具里统一看。</p></div>
        </div>
      </div>`)
  },
  {
    name: '05-作品拉取与媒体库.png',
    html: shell(`
      <div class="canvas">
        <div class="top"><img class="icon" src="${iconData}"><div class="brand"><h1>作品拉取 + 媒体库</h1><p>按主播做素材归档，不再一堆文件乱飞</p></div></div>
        <div class="mock panel">
          <div class="panel-head"><span class="dot"></span><span class="dot y"></span><span class="dot g"></span><span class="title">作品拉取 / 媒体资产</span></div>
          <div class="mock">
            <div class="tabs"><div class="tab on">作品拉取</div><div class="tab">媒体库</div><div class="tab">主播库</div></div>
            <div class="stat"><div><b>128</b><span>已检查</span></div><div><b>12</b><span>新增作品</span></div><div><b>0</b><span>重复拉取</span></div></div>
            <div class="grid" style="margin-top:22px">
              <div class="card"><h3>增量拉取</h3><p>记录已拉取作品 ID 和上次拉取时间，避免重复下载。</p></div>
              <div class="card"><h3>按主播归档</h3><p>直播录制、作品文件、音频素材按主播聚合管理。</p></div>
              <div class="card"><h3>打开目录</h3><p>一键打开保存目录，方便直接剪辑和备份。</p></div>
              <div class="card"><h3>百度网盘可选</h3><p>需要时可配置上传能力，不需要则完全本地保存。</p></div>
            </div>
          </div>
        </div>
        <div class="foot">提示：作品拉取、弹幕发送等能力受用户登录状态和平台策略影响，不建议在商品页承诺“永久稳定”。</div>
      </div>`)
  }
];

async function capture(win, page) {
  const htmlPath = path.join(tempDir, page.name.replace(/\.png$/, '.html').replace(/[^\w.-]/g, '_'));
  fs.writeFileSync(htmlPath, page.html, 'utf8');
  await win.loadFile(htmlPath);
  await new Promise(resolve => setTimeout(resolve, 400));
  const image = await win.capturePage();
  fs.writeFileSync(path.join(outDir, page.name), image.toPNG());
  fs.rmSync(htmlPath, { force: true });
}

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    show: false,
    width: 1242,
    height: 1660,
    webPreferences: { offscreen: true, sandbox: false, webSecurity: false }
  });
  for (const page of pages) await capture(win, page);
  win.destroy();
  fs.rmSync(tempDir, { recursive: true, force: true });
  app.quit();
}).catch(error => {
  console.error(error);
  fs.rmSync(tempDir, { recursive: true, force: true });
  app.quit();
});
