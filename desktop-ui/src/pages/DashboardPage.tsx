import { ActionIcon, Button, Group, Switch, Text, TextInput, Tooltip } from '@mantine/core';
import { FolderOpen, Plus, Square, Trash2, Video } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../api';
import { Empty, PageGrid, Panel, StatusBadge, anchorLiveUrl, formatBytes } from '../components';
import type { Anchor, AppState } from '../types';

export function DashboardPage({ state, refresh, notify }: { state: AppState; refresh: () => Promise<void>; notify: (m: string, error?: boolean) => void }) {
  const [room, setRoom] = useState('');
  const [logs, setLogs] = useState<string[]>([]);
  const [cursor, setCursor] = useState(0);
  const [detailed, setDetailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const running = !!state.status?.running;
  useEffect(() => { setCursor(0); setLogs([]); }, [detailed]);
  useEffect(() => {
    const poll = async () => { try { const data = await api<any>(`/api/logs?cursor=${cursor}&detail=${detailed ? 1 : 0}`); if (data.lines?.length) setLogs(value => [...value, ...data.lines].slice(-1000)); setCursor(data.cursor || 0); } catch {} };
    poll(); const timer = window.setInterval(poll, 1000); return () => clearInterval(timer);
  }, [cursor, detailed]);
  const act = async (fn: () => Promise<any>, message: string) => { setBusy(true); try { await fn(); await refresh(); notify(message); } catch (e) { notify((e as Error).message, true); } finally { setBusy(false); } };
  const addRoom = () => act(async () => { await api('/api/anchors', { name: '未命名主播', profile_url: room, live_url: room }); setRoom(''); }, '主播已加入数据集');
  const toggle = (item: Anchor, active: boolean) => act(() => api(`/api/anchors/${item.id}`, { enabled_recording: active }), active ? '已启用录制' : '已暂停录制');
  const remove = (item: Anchor) => { if (confirm(`确定从主播数据集中删除 ${item.name} 吗？`)) act(() => api(`/api/anchors/${item.id}`, undefined, 'DELETE'), '主播已删除'); };
  const recordings = state.recording_groups || [];
  const roomStates = state.status?.room_states || {};
  const displayState = (anchor: Anchor) => {
    if (!anchorLiveUrl(anchor)) return 'error';
    if (anchor.enabled_recording === false) return 'paused';
    const runtime = roomStates[anchor.name]?.state;
    if (runtime === 'recording' || runtime === 'live') return runtime;
    if (running) return 'waiting';
    return anchor.last_live_status || 'unknown';
  };
  const activeCount = state.anchors.filter(anchor => displayState(anchor) === 'live' || displayState(anchor) === 'recording').length;
  const recordingCount = state.anchors.filter(anchor => displayState(anchor) === 'recording').length;
  return <PageGrid>
    <div className="column">
      <Panel title="主播开播状态" badge={<Group gap="xs"><StatusBadge value={recordingCount ? 'recording' : activeCount ? 'live' : running ? 'waiting' : 'stopped'} /><Text c="dimmed" size="sm">{recordingCount} 个录制中 · {activeCount} 个已开播</Text></Group>}>
        <div className="recordingSummary"><div><strong>{state.anchors.filter(a => a.enabled_recording && anchorLiveUrl(a)).length}</strong><span>监控主播</span></div><div className="live"><strong>{activeCount}</strong><span>当前开播</span></div><div className="recording"><strong>{recordingCount}</strong><span>正在录制</span></div></div>
        <div className="list roomStatusList">{state.anchors.length ? state.anchors.map(item => { const runtime=roomStates[item.name]; const status=displayState(item); return <div className={`listRow roomStatus ${status}`} key={item.id}>
          <Switch checked={item.enabled_recording !== false} disabled={running || busy || !anchorLiveUrl(item)} onChange={e => toggle(item, e.currentTarget.checked)} />
          <div className="grow"><Group gap="xs"><span className="roomStateDot"/><Text fw={700}>{item.name}</Text><StatusBadge value={status} /></Group><Text size="xs" c="dimmed" truncate>{runtime?.path ? `正在写入：${runtime.path}` : status === 'waiting' ? '录制服务正在巡检，开播后会自动开始录制' : status === 'live' ? '已检测到开播，正在准备录制' : anchorLiveUrl(item) || '尚未解析直播间地址'}</Text>{runtime?.updated_at&&<Text size="xs" c="dimmed">状态更新：{new Date(runtime.updated_at*1000).toLocaleTimeString()}</Text>}</div>
          <Tooltip label={running ? '录制期间不可删除' : '删除'}><ActionIcon variant="subtle" color="red" disabled={running} onClick={() => remove(item)}><Trash2 size={17} /></ActionIcon></Tooltip>
        </div>}) : <Empty>添加直播间后即可巡检并自动录制</Empty>}</div>
        <Group className="addBar" wrap="nowrap"><TextInput value={room} onChange={e => setRoom(e.currentTarget.value)} onKeyDown={e => e.key === 'Enter' && addRoom()} placeholder="粘贴直播间地址，加入统一主播库" leftSection={<Plus size={16} />} flex={1} /><Button disabled={!room.trim()} onClick={addRoom}>添加</Button></Group>
      </Panel>
      <Panel title="运行日志" actions={<Group gap="xs"><Button size="xs" variant="subtle" onClick={() => setDetailed(v => !v)}>{detailed ? '只看关键节点' : '显示详细日志'}</Button><Button size="xs" variant="subtle" onClick={() => setLogs([])}>清空</Button></Group>}>
        <pre className="logBox">{logs.length ? logs.join('\n') : '等待录制服务输出…'}</pre>
      </Panel>
    </div>
    <div className="column">
      <Panel title="录制控制" badge={<StatusBadge value={running ? 'recording' : 'paused'} />}>
        <div className="heroAction"><div><Text fw={800} size="xl">{running ? '录制服务运行中' : '准备开始录制'}</Text><Text c="dimmed" mt={4}>{running ? '正在巡检已启用直播间，开播后自动保存。' : '使用设置页中的画质、格式和分段配置。'}</Text></div><Group><Button leftSection={<Video size={18} />} disabled={running || busy} loading={busy && !running} onClick={() => act(() => api('/api/start', { settings: state.settings }), '录制服务已启动')}>开始录制</Button><Button color="red" variant="light" leftSection={<Square size={17} />} disabled={!running || busy} loading={busy && running} onClick={() => act(() => api('/api/stop', {}), '录制已停止并保存')}>停止并保存</Button></Group></div>
      </Panel>
      <Panel title="最近录像" badge={<Text c="dimmed" size="sm">{recordings.length} 场</Text>} actions={<Button size="xs" variant="subtle" leftSection={<FolderOpen size={15} />} onClick={() => api('/api/open-output', {}).catch(e => notify(e.message, true))}>打开目录</Button>}>
        <div className="list">{recordings.length ? recordings.slice(0, 12).map((group: any, index: number) => <div className="listRow" key={group.id || index}><div className="fileIcon"><Video size={18} /></div><div className="grow"><Text fw={650}>{group.name || group.anchor || '录像'}</Text><Text size="xs" c="dimmed">{group.segment_count || group.files?.length || 1} 个文件 · {formatBytes(group.total_size || group.size)} · {group.modified ? new Date(group.modified * 1000).toLocaleString() : ''}</Text></div></div>) : <Empty>还没有本地录像</Empty>}</div>
      </Panel>
    </div>
  </PageGrid>;
}
