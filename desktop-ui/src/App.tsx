import { ActionIcon, Badge, Button, Drawer, Group, Loader, Progress, Text, Tooltip, useMantineColorScheme } from '@mantine/core';
import { Activity, Archive, CircleUserRound, CloudUpload, Headphones, Library, Menu, PanelLeftClose, Radio, RadioTower, Settings, Square, Video } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { api, audioStreamUrl } from './api';
import type { AppState } from './types';
import { anchorLiveUrl } from './components';
import { DashboardPage } from './pages/DashboardPage';
import { AnchorsPage } from './pages/AnchorsPage';
import { InteractionPage } from './pages/InteractionPage';
import { WorksPage } from './pages/WorksPage';
import { LibraryPage } from './pages/LibraryPage';
import { SettingsPage } from './pages/SettingsPage';

const navigation = [
  ['record', '工作台', Video], ['anchors', '主播库', CircleUserRound], ['interact', '直播监听', Radio],
  ['works', '作品拉取', Archive], ['library', '媒体与归档', Library], ['settings', '设置', Settings],
] as const;
const pageMeta: Record<string, [string, string]> = {
  record: ['本地录制', '管理直播间与录制状态'], anchors: ['主播库', '搜索、编辑并统一管理主播'],
  interact: ['直播监听', '弹幕、礼物与直播声音'], works: ['作品拉取', '增量下载公开作品并自动去重'],
  library: ['媒体与归档', '浏览本地文件并管理百度网盘上传'], settings: ['设置', '录制、账号、后台与界面偏好'],
};
const emptyState: AppState = { rooms: [], anchors: [], settings: {}, status: {}, baidupan: {}, auth: {}, update: {}, interaction: {}, work_pull: {}, recordings: [], recording_groups: [] };

export function App() {
  const { setColorScheme } = useMantineColorScheme();
  const [state, setState] = useState<AppState>(emptyState); const [ready, setReady] = useState(false); const [page, setPage] = useState(localStorage.getItem('liveRecorderLastView') || 'record'); const [sidebar, setSidebar] = useState(true); const [compact, setCompact] = useState(localStorage.getItem('liveRecorderCompactMode') === '1'); const [theme, setThemeState] = useState(localStorage.getItem('liveRecorderTheme') || 'dark'); const [toast, setToast] = useState<{message:string;error:boolean}>();
  const [quickAudioUrl, setQuickAudioUrl] = useState('');
  const [tasksOpen, setTasksOpen] = useState(false);
  const notify = useCallback((message: string, error = false) => { setToast({message,error}); window.setTimeout(() => setToast(undefined), error ? 5200 : 3000); }, []);
  const refresh = useCallback(async () => { try { setState(await api<AppState>('/api/state')); setReady(true); } catch (e) { notify((e as Error).message, true); } }, [notify]);
  useEffect(() => { refresh(); const timer = setInterval(refresh, 4000); return () => clearInterval(timer); }, [refresh]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('liveRecorderTheme', theme);
    setColorScheme(['dark', 'midnight', 'forest', 'wine'].includes(theme) ? 'dark' : 'light');
  }, [setColorScheme, theme]);
  const navigate = (value: string) => { setPage(value); localStorage.setItem('liveRecorderLastView', value); };
  const setCompactMode = async () => { const next = !compact; try { await window.liveRecorderDesktop?.setCompactMode(next); setCompact(next); localStorage.setItem('liveRecorderCompactMode', next ? '1' : '0'); if (next) navigate('interact'); } catch (e) { notify((e as Error).message, true); } };
  const quickRecord = async () => { try { await api(state.status.running ? '/api/stop' : '/api/start', state.status.running ? {} : {settings: state.settings}); await refresh(); notify(state.status.running ? '录制已停止并保存' : '录制服务已启动'); } catch (e) { notify((e as Error).message, true); } };
  const selectedAnchor = () => state.anchors.find(anchor=>anchor.id===localStorage.getItem('liveRecorderSelectedAnchor')) || state.anchors.find(anchor=>!!anchorLiveUrl(anchor));
  const quickListen = async () => { const anchor=selectedAnchor(); try { await api(state.interaction.listening ? '/api/interaction/stop' : '/api/interaction/start', state.interaction.listening ? {} : {anchor_id:anchor?.id}); await refresh(); notify(state.interaction.listening ? '监听已停止' : '弹幕监听已连接'); } catch (e) { notify((e as Error).message, true); } };
  const quickAudio = async () => { try { if (quickAudioUrl) { setQuickAudioUrl(''); await api('/api/interaction/audio-stop', {}); notify('直播声音已停止'); return; } const anchor=selectedAnchor(); const data = await api<any>('/api/interaction/audio-source', {anchor_id:anchor?.id}); setQuickAudioUrl(audioStreamUrl(data.audio.stream_id)); notify('直播声音已开始播放'); } catch (e) { notify((e as Error).message, true); } };
  const [title, subtitle] = pageMeta[page] || pageMeta.record;
  const recordingCount = Object.values(state.status?.room_states || {}).filter((item:any)=>item?.state==='recording').length;
  const uploadItems = (state.baidupan?.items || state.baidupan?.queue || []) as any[];
  const activeUploads = uploadItems.filter(item=>['pending','uploading'].includes(item.status));
  const activeTaskCount = (state.status.running ? 1 : 0) + (state.interaction.listening ? 1 : 0) + activeUploads.length + (state.work_pull?.running ? 1 : 0);
  if (!ready) return <div className="loading"><Loader /><Text c="dimmed">正在连接本地服务…</Text></div>;
  return <div className={`app ${sidebar ? '' : 'sidebarCollapsed'} ${compact ? 'compact' : ''}`}>
    <aside className="sidebar"><div className="brand"><div className="brandMark"><RadioTower size={22} /></div><div className="brandCopy"><Text fw={850}>播录助手</Text><Text size="xs" c="dimmed">本地直播工作台</Text></div></div><nav>{navigation.map(([key,label,Icon])=><button key={key} className={page===key?'active':''} onClick={()=>navigate(key)}><Icon size={19}/><span>{label}</span></button>)}</nav><Text className="sidebarFoot" size="xs" c="dimmed">所有数据仅保存在本机</Text></aside>
    <section className="workspace"><header className="topbar"><Group gap="sm" wrap="nowrap"><Tooltip label={sidebar?'收起侧栏':'展开侧栏'}><ActionIcon variant="subtle" onClick={()=>setSidebar(v=>!v)}>{sidebar?<PanelLeftClose size={19}/>:<Menu size={19}/>}</ActionIcon></Tooltip><div><Text fw={850} size="lg">{title}</Text><Text size="xs" c="dimmed">{subtitle}</Text></div></Group><Group gap="xs" wrap="nowrap"><span className={`statusPill ${state.status.running?'on':''}`}><span/>{state.status.running?'录制服务运行中':'录制服务未启动'}</span><span className={`statusPill ${state.interaction.listening?'on':''}`}><span/>{state.interaction.listening?'监听中':'未监听'}</span><Button size="xs" variant={state.status.running?'light':'filled'} color={state.status.running?'red':'blue'} leftSection={state.status.running?<Square size={14}/>:<Video size={15}/>} onClick={quickRecord}>{state.status.running?'停录':'录制'}</Button><Button size="xs" variant="light" leftSection={state.interaction.listening?<Square size={14}/>:<Radio size={15}/>} onClick={quickListen}>{state.interaction.listening?'停听':'监听'}</Button><Button size="xs" variant="light" color={quickAudioUrl?'red':'blue'} leftSection={quickAudioUrl?<Square size={14}/>:<Headphones size={15}/>} onClick={quickAudio}>{quickAudioUrl?'停声':'声音'}</Button><Button size="xs" variant="default" leftSection={<Activity size={14}/>} onClick={()=>setTasksOpen(true)}>任务{activeTaskCount ? ` ${activeTaskCount}` : ''}</Button><Button size="xs" variant="default" onClick={setCompactMode}>{compact?'退出小窗':'小窗模式'}</Button>{quickAudioUrl&&<audio src={quickAudioUrl} autoPlay onEnded={()=>setQuickAudioUrl('')} />}</Group></header>
      <main className="content">{page==='record'&&<DashboardPage state={state} refresh={refresh} notify={notify}/>} {page==='anchors'&&<AnchorsPage state={state} refresh={refresh} notify={notify} navigate={navigate}/>} {page==='interact'&&<InteractionPage state={state} refresh={refresh} notify={notify}/>} {page==='works'&&<WorksPage state={state} notify={notify}/>} {page==='library'&&<LibraryPage state={state} refresh={refresh} notify={notify}/>} {page==='settings'&&<SettingsPage state={state} refresh={refresh} notify={notify} theme={theme} setTheme={setThemeState}/>}</main>
    </section><Drawer opened={tasksOpen} onClose={()=>setTasksOpen(false)} position="right" size="md" title="后台任务中心"><div className="taskCenter"><div className="taskCard"><Group justify="space-between"><Group gap="sm"><Video size={19}/><div><Text fw={750}>自动录制</Text><Text size="xs" c="dimmed">{state.status.running ? `${recordingCount} 位主播正在录制` : '服务未启动'}</Text></div></Group><Badge color={recordingCount?'red':state.status.running?'yellow':'gray'} variant="light">{recordingCount?'录制中':state.status.running?'巡检中':'已停止'}</Badge></Group></div><div className="taskCard"><Group justify="space-between"><Group gap="sm"><Radio size={19}/><div><Text fw={750}>直播监听</Text><Text size="xs" c="dimmed">{state.interaction.room_url || '尚未选择主播'}</Text></div></Group><Badge color={state.interaction.listening?'green':'gray'} variant="light">{state.interaction.listening?'监听中':'未运行'}</Badge></Group></div><div className="taskCard"><Group justify="space-between"><Group gap="sm"><CloudUpload size={19}/><div><Text fw={750}>百度网盘上传</Text><Text size="xs" c="dimmed">{activeUploads.length ? `${activeUploads.length} 个文件处理中` : '队列空闲'}</Text></div></Group><Badge color={activeUploads.length?'blue':'gray'} variant="light">{activeUploads.length?'上传中':'空闲'}</Badge></Group>{activeUploads.slice(0,3).map(item=><div key={item.id} className="taskProgress"><Group justify="space-between" gap="xs" wrap="nowrap"><Text size="xs" truncate>{item.record_name||item.name||'录像文件'}</Text><Text size="xs">{Math.round(Number(item.progress)||0)}%</Text></Group><Progress value={Number(item.progress)||0} size="xs" mt={4}/></div>)}</div><div className="taskCard"><Group justify="space-between"><Group gap="sm"><Archive size={19}/><div><Text fw={750}>作品拉取</Text><Text size="xs" c="dimmed">{state.work_pull?.message || '尚未运行'}</Text></div></Group><Badge color={state.work_pull?.running?'blue':'gray'} variant="light">{state.work_pull?.running?'运行中':'空闲'}</Badge></Group></div></div></Drawer>{toast&&<div className={`toast ${toast.error?'error':''}`}>{toast.message}</div>}
  </div>;
}
