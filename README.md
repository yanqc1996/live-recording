# 播录助手

播录助手是一款面向本地使用的直播素材工作台，基于原直播录制能力扩展了 Electron 桌面界面、主播库、授权码、直播互动、作品拉取、媒体库和可选百度网盘上传。

它的目标不是让用户折腾命令行，而是把“添加主播 → 本地录制 → 弹幕观察 → 作品拉取 → 素材归档”做成一个可以交付给普通用户使用的桌面应用。

> 当前打包产物主要面向 macOS Apple Silicon，也就是 M1 / M2 / M3 / M4 系列 Mac。Windows 版本需要在 Windows 环境单独构建。

## 功能概览

- 本地直播录制
  - 支持直播间地址管理
  - 支持画质、格式、分段时长、本地保存目录配置
  - 支持录制完成后转 MP4
  - 默认只保存到本机

- 主播库
  - 支持按主播配置主页地址、分享链接或直播间地址
  - 主播配置可统一用于录制、直播互动、作品拉取和媒体库
  - 支持开播状态巡检

- 抖音账号登录
  - Electron 内置登录窗口
  - 用户扫码登录，不需要手动输入 Cookie
  - 登录状态用于直播监听、作品拉取等功能

- 直播互动
  - 支持监听直播间弹幕和用户信息
  - 支持礼物贡献榜展示
  - 支持发送弹幕能力检测
  - 支持工作模式，弱化无关信息，保留核心弹幕

- 只听音频
  - 可获取直播音频源
  - 适合不方便看视频时后台听声音和看弹幕
  - 内置音频自动重连机制

- 作品拉取
  - 支持用户主页、分享链接或 `sec_user_id`
  - 手动触发的一次性拉取任务，不是同步任务
  - 按作品 ID 和上次拉取时间去重
  - 已记录作品即使本地删除，默认也不会重复拉取

- 媒体库
  - 按主播聚合本地录制、作品、音频和图片素材
  - 支持查看文件数量、大小、类型和最近更新时间
  - 支持一键打开本地目录

- 百度网盘上传，可选
  - 可配置录制完成后自动入队上传
  - 支持按主播创建网盘目录
  - 支持失败重试
  - 打包版内置 `bypy`，用户不需要额外安装 Python 或命令行工具

- 买断授权
  - 一机一码
  - 本地激活
  - 未激活时录制、互动、作品拉取、上传等核心功能会被锁定

## 交付包

当前 macOS 用户交付包位于：

```text
release/播录助手-v0.1.0-mac-arm64-用户交付包/
```

包含：

```text
播录助手-0.1.0-arm64.dmg
播录助手-0.1.0-arm64-mac.zip
首次启动引导.txt
播录助手图标预览.png
```

闲鱼上架素材包位于：

```text
release/咸鱼上架素材包/
release/咸鱼上架素材包.zip
```

## 用户安装流程

macOS 用户：

1. 双击打开 `播录助手-0.1.0-arm64.dmg`
2. 将 `播录助手.app` 拖入“应用程序”
3. 第一次打开如果提示“无法验证开发者”，请右键点击 app，选择“打开”
4. 打开软件后复制“当前设备码”
5. 卖家根据设备码生成授权码
6. 用户粘贴授权码并点击“激活授权”

详细步骤见：

```text
首次启动引导.txt
```

## 授权码生成

用户把软件首页显示的设备码发给卖家后，在项目目录执行：

```bash
python3 scripts/generate_license.py --device 用户设备码 --customer "买家昵称" --order "订单号"
```

示例：

```bash
python3 scripts/generate_license.py --device 2980-8709-BCFE-2F1D --customer "测试用户" --order "test-order-001"
```

脚本会输出 `LR1-` 开头的授权码。把整段授权码发给用户即可。

授权码内部绑定：

- 产品标识
- 授权类型
- 当前设备码
- 买家备注
- 订单号
- 签发时间

当前授权方案是轻量本地授权，用于防止普通转发安装包；不是强 DRM。如果后续正式商业化，可以升级为联网授权和设备解绑后台。

## 本地开发运行

安装 Node 依赖：

```bash
npm install
```

安装 Python 依赖：

```bash
python3 -m pip install -r requirements.txt -r requirements-build.txt
```

启动 Electron 桌面版：

```bash
npm run desktop
```

也可以只启动本地 Web 控制台：

```bash
python3 desktop_app.py
```

本地 Web 控制台只监听 `127.0.0.1`，启动后会生成带 token 的访问地址。

## 打包

生成当前平台桌面安装包：

```bash
npm run desktop:dist
```

打包流程会先执行：

```bash
python3 scripts/build_desktop_runtime.py
```

它会使用 PyInstaller 构建内置 Python 运行时，并把当前平台的：

- Python 运行时
- Node.js
- FFmpeg
- bypy
- gmssl
- 前端静态界面
- 抖音签名相关静态资源
- 启动引导文档

一起放入 Electron 应用。

因此最终用户不需要安装 Python、Node.js、FFmpeg 或 bypy。

### macOS

macOS 包必须在 macOS 上构建。

当前产物：

```text
dist/播录助手-0.1.0-arm64.dmg
dist/播录助手-0.1.0-arm64-mac.zip
```

当前 app 未做 Apple Developer ID 签名和 notarization，所以首次打开会出现系统安全提示。正式公开分发前建议补充：

- Apple Developer ID 签名
- notarization 公证
- 更完整的许可证和第三方依赖声明

### Windows

Windows 包需要在 Windows 环境构建。原因是项目内置的 Python 运行时需要通过 PyInstaller 生成 Windows `.exe`，不能直接在 macOS 上交叉生成。

推荐 Windows 构建环境：

- Windows 10 / 11
- Node.js 22.12+
- Python 3.11
- Git

在 Windows 项目目录执行：

```bash
npm install
npm run desktop:dist
```

预期输出：

```text
dist/
├── 播录助手 Setup 0.1.0.exe
└── 播录助手 0.1.0.exe
```

## 目录说明

```text
.
├── desktop/                       # Electron 前端页面
├── electron/                      # Electron 主进程和 preload
├── desktop_app.py                 # 本地桌面后端 API
├── desktop_core.py                # 录制配置和录制进程控制
├── desktop_douyin.py              # 抖音直播互动、音频、礼物榜等能力
├── desktop_work_pull.py           # 用户作品拉取
├── desktop_anchors.py             # 主播库
├── desktop_media_library.py       # 媒体库扫描
├── desktop_baidupan.py            # 百度网盘上传队列
├── desktop_license.py             # 本地买断授权
├── douyin_static/                 # 抖音签名、protobuf 等静态资源
├── douyin_work_pull/              # 作品拉取状态
├── scripts/
│   ├── build_desktop_runtime.py   # 构建内置运行时
│   ├── generate_license.py        # 生成买断授权码
│   ├── upload_to_baidu_netdisk.py # 百度网盘上传脚本
│   └── generate_xianyu_assets.cjs # 生成闲鱼宣传图
├── packaging/                     # 打包默认配置
├── release/                       # 用户交付包和上架素材
├── config/                        # 本地配置
├── main.py                        # 原录制入口
├── package.json                   # Electron 打包配置
└── 首次启动引导.txt
```

## 使用注意事项

- 本工具仅用于个人本地录制、素材整理和直播观察。
- 请勿用于批量搬运、侵权传播、违规营销或其他违反平台规则的用途。
- 请自行确认录制、下载、保存和使用内容的版权与授权。
- 软件不提供账号、不提供代登录、不提供 Cookie。
- 部分功能需要用户自行登录抖音网页账号。
- 第三方平台接口可能变化，登录状态、验证码、风控和接口调整都可能影响部分功能。
- 弹幕发送依赖网页端安全字段，不承诺所有账号和直播间都可稳定发送。
- 百度网盘上传稳定性受百度接口、网络和账号授权状态影响。

## 售卖建议

建议定位为：

```text
本地直播录制工具 / 主播素材管理工具 / 直播弹幕观察工具 / 本地媒体归档工具
```

不建议在商品页强调或承诺：

```text
爬虫、破解、绕过风控、批量搬运、私密作品获取、自动刷弹幕、永久稳定
```

建议价格：

- 首批测试价：¥99
- 标准买断价：¥129 - ¥169
- 含远程安装指导：¥199

## 致谢与说明

本项目基于原直播录制项目能力进行了桌面化和本地产品化改造。当前 README 主要描述本仓库的“播录助手”桌面应用版本。原命令行录制能力仍保留在 `main.py`、`src/`、`config/` 等目录中。

请在遵守相关平台规则、法律法规和内容版权要求的前提下使用本工具。
