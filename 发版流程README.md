# 播录助手发版流程 README

这份文档用于记录「播录助手」的手动发版和半自动更新流程。

当前方案不是全自动更新：软件只负责检查 `release/update.json`，发现新版本后打开下载地址，用户手动下载安装新版。

## 核心概念

### 1. `dist/` 是本地打包原始产物

执行：

```bash
npm run desktop:dist
```

会在 `dist/` 里生成 Electron 原始安装包，例如：

```text
dist/播录助手-0.1.3-arm64.dmg
dist/播录助手-0.1.3-arm64-mac.zip
```

这里的文件名是中文，适合本机查看，但不建议直接用于 GitHub Release 自动更新下载链接。

### 2. `release/github-release/v版本号/` 是 GitHub Release 上传目录

执行：

```bash
python3 scripts/prepare_release.py --repo yanqc1996/live-recording --notes "更新说明" --include-xianyu-assets
```

会生成：

```text
release/github-release/v0.1.3/
```

这个目录里的文件才是建议上传到 GitHub Release 的文件，例如：

```text
BoluAssistant-0.1.3-arm64.dmg
BoluAssistant-0.1.3-arm64-mac.zip
BoluAssistant-v0.1.3-mac-arm64-delivery.zip
update.json
咸鱼上架素材包.zip
```

注意：`BoluAssistant-xxx.dmg` 是脚本从 `dist/播录助手-xxx.dmg` 复制并重命名出来的英文资产名。这样做是为了避免 GitHub Release 下载地址里出现中文 URL 编码，提升自动更新稳定性。

### 3. `release/update.json` 是软件检查更新的清单

软件默认读取：

```text
https://raw.githubusercontent.com/yanqc1996/live-recording/main/release/update.json
```

这个地址对应本地文件：

```text
release/update.json
```

所以每次发版后，都必须提交并推送 `release/update.json`。

`.gitignore` 当前会忽略 `release/` 里的大安装包，但允许提交：

```text
release/update.json
release/update.example.json
```

## 标准发版流程

下面以发布 `0.1.4` 为例。

### 1. 修改版本号

修改：

```text
package.json
package-lock.json
```

把顶部项目版本改成目标版本，例如：

```json
"version": "0.1.4"
```

如果是测试发布链路，也可以在 `desktop/index.html` 里同步改测试标识：

```text
发布链路测试：v0.1.4
```

### 2. 本地打包

#### macOS

执行：

```bash
npm run desktop:dist
```

成功后检查：

```bash
ls -lh dist/播录助手-0.1.4-arm64.dmg
```

如果文件存在，说明本地 DMG 已打出。

#### Windows x64

Windows 安装包必须在 Windows 10/11 x64 环境构建，不能在 macOS 上交叉
生成。构建机器需要先安装：

- Node.js 22.12 或更高版本
- Python 3.11 64 位，并加入 `PATH`
- Git

在 Windows PowerShell 中进入项目目录，然后执行：

```powershell
npm ci
python scripts/build_desktop_runtime.py
npx electron-builder --win nsis portable --x64
```

当前不直接使用 `npm run desktop:dist`，因为其中的 Python 构建命令是
`python3`，而 Windows 默认通常使用 `python`。上面的命令会依次：

1. 按 `package-lock.json` 安装 Node/Electron 构建依赖；
2. 生成 Windows 版 Python 运行时，并内置 `node.exe` 和 `ffmpeg.exe`；
3. 生成 NSIS 安装包和免安装便携版。

预期产物位于：

```text
dist/
├── 播录助手 Setup 0.1.4.exe
└── 播录助手 0.1.4.exe
```

带 `Setup` 的文件是安装包，另一个是 portable 便携版。打包前不要复用从
macOS 复制过来的 `build/desktop-runtime` 或 `dist/` 构建产物。

注意：当前 `scripts/prepare_release.py` 和 `release/update.json` 的标准
流程仍以 macOS DMG 为主。Windows EXE 可以先手动上传到 GitHub Release；
如果需要让 Windows 客户端自动打开正确的 EXE 下载地址，还需要把更新清单
改成按平台提供下载地址。

### 3. 生成 GitHub Release 上传目录

执行：

```bash
python3 scripts/prepare_release.py \
  --repo yanqc1996/live-recording \
  --notes "这里填写本次更新说明" \
  --include-xianyu-assets
```

示例：

```bash
python3 scripts/prepare_release.py \
  --repo yanqc1996/live-recording \
  --notes "发布链路测试 v0.1.4：验证半自动更新流程。" \
  --include-xianyu-assets
```

脚本会生成：

```text
release/github-release/v0.1.4/
release/update.json
```

并且 `release/update.json` 中的 `download_url` 会指向英文 DMG，例如：

```text
https://github.com/yanqc1996/live-recording/releases/download/v0.1.4/BoluAssistant-0.1.4-arm64.dmg
```

### 4. 提交代码和 update.json

执行：

```bash
git add package.json package-lock.json desktop/index.html scripts/prepare_release.py release/update.json
git commit -m "Release v0.1.4"
git push
```

如果本次没有修改 `desktop/index.html` 或 `scripts/prepare_release.py`，可以不 add 它们。

不要执行：

```bash
git push --tags
```

SourceTree 里也不要勾选：

```text
Push all tags
```

普通代码提交只需要推当前分支。

### 5. 创建 GitHub Release

打开 GitHub 仓库：

```text
https://github.com/yanqc1996/live-recording
```

进入：

```text
Releases -> Draft a new release
```

填写：

```text
Tag: v0.1.4
Title: 播录助手 v0.1.4
```

上传这个目录里的文件：

```text
release/github-release/v0.1.4/
```

至少上传：

```text
BoluAssistant-0.1.4-arm64.dmg
update.json
```

建议一起上传：

```text
BoluAssistant-0.1.4-arm64-mac.zip
BoluAssistant-v0.1.4-mac-arm64-delivery.zip
咸鱼上架素材包.zip
```

然后点击发布 Release。

### 6. 验证 update.json 是否可访问

浏览器打开：

```text
https://raw.githubusercontent.com/yanqc1996/live-recording/main/release/update.json
```

应该能看到类似：

```json
{
  "version": "0.1.4",
  "title": "播录助手 v0.1.4",
  "notes": "这里填写本次更新说明",
  "download_url": "https://github.com/yanqc1996/live-recording/releases/download/v0.1.4/BoluAssistant-0.1.4-arm64.dmg",
  "published_at": "2026-07-21"
}
```

如果这里 404，通常是：

- `release/update.json` 没有提交到 GitHub；
- 仓库不是 public；
- 分支不是 `main`；
- 路径不对。

### 7. 验证 DMG 下载地址

浏览器打开 `update.json` 里的 `download_url`。

例如：

```text
https://github.com/yanqc1996/live-recording/releases/download/v0.1.4/BoluAssistant-0.1.4-arm64.dmg
```

能开始下载 DMG，说明 GitHub Release asset 上传成功。

如果这里 404，通常是：

- GitHub Release 的 tag 不叫 `v0.1.4`；
- 没有上传 `BoluAssistant-0.1.4-arm64.dmg`；
- 上传的文件名和 `update.json` 里的文件名不完全一致。

### 8. 用旧版软件检查更新

打开旧版播录助手，进入「软件更新」，点击：

```text
检查更新
```

正常结果：

```text
发现 0.1.4
```

点击「打开下载」，应该会打开 `update.json` 里的 `download_url`。

## 常见问题

### 为什么 `dist/` 里没有 BoluAssistant？

正常。

`dist/` 是 Electron 原始打包目录，文件名是：

```text
播录助手-版本号-arm64.dmg
```

`BoluAssistant-版本号-arm64.dmg` 是 `scripts/prepare_release.py` 在：

```text
release/github-release/v版本号/
```

里复制并重命名出来的 GitHub Release 上传文件。

### 为什么不用中文 DMG 文件名做下载地址？

中文文件名可以用，但 GitHub Release 下载 URL 里会变成 URL 编码，例如：

```text
%E6%92%AD%E5%BD%95...
```

手动复制、上传、比对时更容易出错。为了稳定，GitHub Release asset 使用英文名。

### 为什么软件检查更新 404？

先分别验证两个地址：

1. `update.json` 地址：

```text
https://raw.githubusercontent.com/yanqc1996/live-recording/main/release/update.json
```

2. `update.json` 里的 `download_url`

如果第一个 404，是 `release/update.json` 没推上去或仓库不可公开访问。

如果第一个正常、第二个 404，是 GitHub Release 资产没有上传成功或文件名/tag 不匹配。

### GitHub 仓库可以是 private 吗？

不建议。

如果仓库是 private，软件无法匿名读取：

```text
raw.githubusercontent.com/.../release/update.json
```

用户也无法匿名下载 Release 安装包。用于发版和更新的仓库或文件地址必须公网可访问。

### macOS 提示“已损坏，无法打开”怎么办？

当前版本未做 Apple Developer ID 签名和 notarization。如果用户从 GitHub、网盘或浏览器下载，macOS 可能添加隔离标记并提示 damaged。

处理方式：

```bash
xattr -dr com.apple.quarantine /Applications/播录助手.app
```

如果 DMG 本身打不开：

```bash
xattr -d com.apple.quarantine ~/Downloads/播录助手-0.1.4-arm64.dmg
```

正式大量售卖时，建议补 Apple Developer ID 签名和公证。

### Tag 怎么管理？

目前只需要保留当前产品版本相关 tag，例如：

```text
0.1.0
v0.1.1
v0.1.2
v0.1.3
v0.1.4
```

不要推送上游旧项目 tag。

普通提交不要用：

```bash
git push --tags
```

如果需要新版本 tag，优先在 GitHub Release 页面创建 `v版本号`。
