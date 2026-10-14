export type InterfaceLanguage = 'en' | 'zh';

const ENGLISH: Record<string, string> = {
  '播录助手': 'Live Studio', '本地直播工作台': 'Local live workspace', '所有数据仅保存在本机': 'All data stays on this Mac',
  '工作台': 'Dashboard', '主播库': 'Creators', '直播监听': 'Live Monitor', '作品拉取': 'Content Sync', '媒体与归档': 'Media & Archive', '设置': 'Settings',
  '本地录制': 'Local Recording', '管理直播间与录制状态': 'Manage live rooms and recording status', '搜索、编辑并统一管理主播': 'Search and manage creators',
  '弹幕、礼物与直播声音': 'Chat, gifts and live audio', '增量下载公开作品并自动去重': 'Sync public posts with automatic deduplication',
  '浏览本地文件并管理百度网盘上传': 'Browse local media and cloud uploads', '录制、账号、后台与界面偏好': 'Recording, account and background preferences',
  '录制服务运行中': 'Recorder running', '录制服务未启动': 'Recorder stopped', '监听中': 'Monitoring', '未监听': 'Not monitoring',
  '停录': 'Stop', '录制': 'Record', '停听': 'Stop', '监听': 'Monitor', '停声': 'Mute', '声音': 'Audio', '任务': 'Tasks', '退出小窗': 'Exit Mini', '小窗模式': 'Mini Mode',
  '收起侧栏': 'Collapse sidebar', '展开侧栏': 'Expand sidebar', '正在连接本地服务…': 'Connecting to local service…',
  '录制总览': 'Recording Overview', '运行事件': 'Activity', '开始录制': 'Start Recording', '停止并保存': 'Stop & Save',
  '监控运行中，等待主播开播': 'Monitoring creators for live sessions',
  '系统会持续巡检已启用主播，检测到开播后自动录制。': 'Enabled creators are checked continuously and recorded automatically when live.',
  '启动后会在后台自动巡检，不需要保持窗口打开。': 'Runs in the background; the window may stay closed.',
  '监控主播': 'Monitored', '当前开播': 'Live Now', '正在录制': 'Recording', '主播实时状态': 'Creator Status', '每 4 秒刷新': 'Refreshes every 4 seconds',
  '等待开播': 'Waiting', '已开播': 'Live', '未开播': 'Offline', '疑似漏录': 'Possible Miss', '直播录制中': 'Recording Live', '状态未知': 'Unknown', '地址异常': 'Invalid URL',
  '录制服务正在巡检，开播后会自动开始录制': 'Watching for the next live session', '已检测到开播，正在准备录制': 'Live detected; preparing recorder',
  '尚未解析直播间地址': 'Live room URL not resolved', '检查回放': 'Check Replay', '添加直播间后即可巡检并自动录制': 'Add a live room to enable automatic recording',
  '粘贴直播间地址，加入统一主播库': 'Paste a live room URL', '添加': 'Add', '最近录像': 'Recent Recordings', '打开目录': 'Open Folder', '还没有本地录像': 'No local recordings yet',
  '发现主播': 'Discover Creators', '昵称 / 抖音号': 'Name / Douyin ID', '输入主播昵称或抖音号': 'Search name or Douyin ID', '搜索': 'Search',
  '请核对抖音号后加入；搜索受限时，可粘贴手机端分享文本。': 'Verify the account ID before adding. You can also paste a mobile share link.',
  '编辑集合': 'Edit Collection', '巡检全部': 'Check All', '筛选已保存主播': 'Filter saved creators', '全部状态': 'All Statuses', '直播中': 'Live', '异常': 'Error', '未巡检': 'Not Checked',
  '没有符合条件的主播': 'No matching creators', '主播数据编辑器': 'Creator Data Editor', '从左侧选择主播后修改完整资料': 'Select a creator to edit their profile',
  '粘贴手机分享': 'Paste Mobile Share', '主页分享文案或链接': 'Profile share text or URL', '解析主播': 'Resolve Creator', '清空': 'Clear', '确认加入主播库': 'Add to Creator Library',
  '暂不解析，直接保存': 'Save Without Resolving', '主播名称': 'Creator Name', '直播间地址': 'Live Room URL',
  '基础资料': 'Profile', '参与自动录制': 'Include in Auto Recording', '高级标识、历史别名与存储': 'Identity, Aliases & Storage',
  '历史昵称：': 'Previous names: ', '合并重复身份': 'Merge Duplicate Identity', '主播数据已保存': 'Creator saved', '重复主播身份已合并': 'Duplicate identities merged',
  '直播间控制': 'Live Room Controls', '选择主播': 'Select Creator', '开始监听': 'Start Monitoring', '停止': 'Stop', '工作模式': 'Work Mode',
  '只听直播声音': 'Live Audio Only', '播放声音': 'Play Audio', '停止声音': 'Stop Audio', '本场礼物与音浪': 'Session Gifts & Points',
  '礼物数量': 'Gifts', '预估音浪': 'Estimated Points', '送礼用户': 'Contributors', '平台值': 'Platform', '本地估算': 'Estimated', '未知': 'Unknown', '价值覆盖率': 'Value Coverage',
  '本场实时贡献榜': 'Live Contributor Ranking', '收到礼物后自动生成本场排行': 'Ranking appears when gifts are received', '礼物贡献榜': 'Platform Gift Ranking', '刷新榜单': 'Refresh Ranking',
  '刷新后显示当前贡献榜': 'Refresh to load the current ranking', '实时消息': 'Live Events', '实时弹幕与用户': 'Live Chat & Viewers', '发送直播间弹幕': 'Send a live chat message', '发送': 'Send',
  '作品入口': 'Content Source', '保存目录（留空使用录像目录）': 'Save Folder (blank uses recording folder)', '选择': 'Choose', '开始拉取作品': 'Start Sync', '打开保存目录': 'Open Save Folder',
  '任务统计': 'Task Summary', '已检查': 'Checked', '新增': 'New', '已下载': 'Downloaded', '跳过': 'Skipped', '失败': 'Failed', '拉取日志': 'Sync Log', '等待开始拉取…': 'Waiting to start…',
  '媒体库': 'Media Library', '主播': 'Creators', '文件': 'Files', '总容量': 'Total Size', '直播场次': 'Live Sessions', '搜索文件': 'Search files', '全部类型': 'All Types',
  '视频': 'Video', '音频': 'Audio', '图片': 'Image', '直播录像': 'Recordings', '作品': 'Posts', '预览': 'Preview', '校验': 'Verify', '已上传': 'Uploaded', '待上传': 'Pending Upload', '上传失败': 'Upload Failed', '队列中': 'Queued',
  '直播场次详情': 'Live Session Details', '本场贡献排行': 'Session Contributor Ranking', '文件清单': 'Files', '检测并开始录制': 'Live detected and recording started', '录制分段': 'Recording segments',
  '合并完整文件': 'Merged recording', '完整性检查': 'Integrity check', '网盘归档': 'Cloud archive',
  '录制设置': 'Recording Settings', '保存': 'Save', '录像保存目录': 'Recording Folder', '画质': 'Quality', '格式': 'Format', '巡检间隔（秒）': 'Check Interval (seconds)', '分段时长（秒）': 'Segment Length (seconds)',
  '磁盘预警（GB）': 'Disk Warning (GB)', '停止录制（GB）': 'Stop Recording (GB)', '启用分段录制': 'Enable segmented recording', '录完转为 MP4': 'Convert to MP4', '转换后删除原文件': 'Delete source after conversion', '使用代理': 'Use proxy', '代理地址': 'Proxy Address',
  '界面偏好': 'Appearance', '主题': 'Theme', '语言': 'Language', '英语（低调模式）': 'English (Discreet)', '中文': 'Chinese',
  '英文模式同时使用较低调的 Live Studio 名称': 'English mode also uses the discreet “Live Studio” app name.',
  '明亮深色': 'Bright Dark', '雾蓝': 'Mist Blue', '暖米': 'Warm Sand', '浅色': 'Light', '纯白': 'Pure White', '午夜蓝': 'Midnight Blue', '森林绿': 'Forest Green', '酒红': 'Wine Red',
  '账号与连接': 'Account & Connection', '账号已登录': 'Signed In', '账号未登录': 'Signed Out', '登录增强': 'Sign In', '重新登录': 'Sign In Again', '刷新发送凭证': 'Refresh Chat Credentials', '退出': 'Sign Out',
  '手动导入 Cookie': 'Import Cookie Manually', '导入': 'Import', '如何从已登录的抖音网页获取 Cookie？': 'How to copy a Cookie from a signed-in Douyin page?',
  '后台与自动运行': 'Background & Automation', '登录后自动启动': 'Launch at Login', '启动时隐藏窗口': 'Launch Hidden', '后台运行时隐藏 Dock 图标': 'Hide Dock Icon in Background', '自动开始录制服务': 'Start Recorder Automatically',
  '任务期间防止整机睡眠': 'Prevent Sleep While Active', '录制通知': 'Recording Notifications', '归档完成通知': 'Archive Notifications', '异常通知': 'Error Notifications',
  '软件更新': 'Software Update', '远程更新 JSON 地址': 'Update Manifest URL', '保存地址': 'Save URL', '检查更新': 'Check for Updates', '打开下载': 'Open Download',
  '后台任务中心': 'Background Tasks', '自动录制': 'Automatic Recording', '服务未启动': 'Not Running', '录制中': 'Recording', '巡检中': 'Monitoring', '已停止': 'Stopped',
  '直播会话': 'Live Session', '未选择主播': 'No Creator Selected', '弹幕': 'Chat', '已连接': 'Connected', '未连接': 'Disconnected', '播放中': 'Playing', '未播放': 'Stopped', '未运行': 'Idle',
  '百度网盘上传': 'Cloud Upload', '队列空闲': 'Queue Idle', '空闲': 'Idle', '录像文件': 'Recording', '尚未运行': 'Not Started', '运行中': 'Running',
  '已完成': 'Completed', '等待中': 'Pending', '上传中': 'Uploading', '已暂停': 'Paused', '已取消': 'Cancelled', '系统': 'System', '关注': 'Follow', '礼物': 'Gift'
};

function translatedText(value: string): string {
  const leading = value.match(/^\s*/)?.[0] || '';
  const trailing = value.match(/\s*$/)?.[0] || '';
  const core = value.trim();
  if (!core) return value;
  if (ENGLISH[core]) return `${leading}${ENGLISH[core]}${trailing}`;
  const patterns: Array<[RegExp, string]> = [
    [/^(\d+) 个文件$/, '$1 files'], [/^(\d+) 场$/, '$1 sessions'], [/^(\d+) 人$/, '$1 people'],
    [/^(\d+) 件礼物$/, '$1 gifts'], [/^(\d+) 音浪$/, '$1 points'], [/^当前 (.+)$/, 'Current $1'],
    [/^任务 (\d+)$/, 'Tasks $1'], [/^价值覆盖率 (\d+)%$/, 'Value coverage $1%'],
    [/^平台值 (\d+)$/, 'Platform $1'], [/^本地估算 (\d+)$/, 'Estimated $1'], [/^未知 (\d+)$/, 'Unknown $1']
  ];
  for (const [pattern, replacement] of patterns) if (pattern.test(core)) return `${leading}${core.replace(pattern, replacement)}${trailing}`;
  return value;
}

function translateElement(root: ParentNode) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  for (const node of nodes) {
    if (node.parentElement?.closest('code, pre')) continue;
    const next = translatedText(node.data);
    if (next !== node.data) node.data = next;
  }
  const elements = root instanceof Element ? [root, ...root.querySelectorAll('*')] : [...root.querySelectorAll('*')];
  for (const element of elements) for (const attribute of ['placeholder', 'title', 'aria-label']) {
    const value = element.getAttribute(attribute);
    if (value) element.setAttribute(attribute, translatedText(value));
  }
}

export function enableEnglishInterface(): () => void {
  document.documentElement.lang = 'en';
  document.title = 'Live Studio';
  translateElement(document.body);
  const observer = new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData' && record.target instanceof Text) {
        const next = translatedText(record.target.data); if (next !== record.target.data) record.target.data = next;
      }
      for (const node of record.addedNodes) if (node instanceof Element) translateElement(node); else if (node instanceof Text) {
        const next = translatedText(node.data); if (next !== node.data) node.data = next;
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  return () => observer.disconnect();
}
