import { ActionIcon, Alert, Badge, Button, Drawer, Group, Switch, Text, TextInput, Tooltip } from '@mantine/core';
import { Activity, FileCheck2, FolderOpen, Plus, Radio, Square, Trash2, TriangleAlert, Video } from 'lucide-react';
import { useState } from 'react';
import { api } from '../api';
import { Empty, PageGrid, Panel, StatusBadge, anchorLiveUrl, formatBytes } from '../components';
import type { Anchor, AppState } from '../types';

export function DashboardPage({ state, refresh, notify, logs, detailed, setDetailed, clearLogs }: { state: AppState; refresh: () => Promise<void>; notify: (m: string, error?: boolean) => void; logs: string[]; detailed: boolean; setDetailed: (value: boolean) => void; clearLogs: () => void }) {
  const [room, setRoom] = useState('');
  const [logsOpen, setLogsOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [replayCandidates,setReplayCandidates]=useState<any[]>([]); const [replayOpen,setReplayOpen]=useState(false); const [replayBusy,setReplayBusy]=useState('');
  const running = !!state.status?.running;
  const act = async (fn: () => Promise<any>, message: string) => { setBusy(true); try { await fn(); await refresh(); notify(message); } catch (e) { notify((e as Error).message, true); } finally { setBusy(false); } };
  const addRoom = () => act(async () => { await api('/api/anchors', { name: '未命名主播', profile_url: room, live_url: room }); setRoom(''); }, '主播已加入数据集');
  const toggle = (item: Anchor, active: boolean) => act(() => api(`/api/anchors/${item.id}`, { enabled_recording: active }), active ? '已启用录制' : '已暂停录制');
  const remove = (item: Anchor) => { if (confirm(`确定从主播数据集中删除 ${item.name} 吗？`)) act(() => api(`/api/anchors/${item.id}`, undefined, 'DELETE'), '主播已删除'); };
  const checkReplay=async(item:Anchor,runtime:any)=>{setReplayBusy('check');try{const result=await api<any>('/api/replays/check',{anchor_id:item.id,since:runtime?.live_detected_at||runtime?.suspected_at||0});setReplayCandidates(result.candidates||[]);setReplayOpen(true);notify(result.candidates?.length?`找到 ${result.candidates.length} 个回放候选`:'未发现平台公开的直播回放');}catch(e){notify((e as Error).message,true)}finally{setReplayBusy('')}};
  const recordings = state.recording_groups || [];
  const roomStates = state.status?.room_states || {};
  const displayState = (anchor: Anchor) => {
    if (!anchorLiveUrl(anchor)) return 'error';
    if (anchor.enabled_recording === false) return 'paused';
    const runtime = roomStates[anchor.id]?.state;
    if (runtime === 'recording' || runtime === 'live' || runtime === 'missed') return runtime;
    if (running) return 'waiting';
    return anchor.last_live_status || 'unknown';
  };
  const activeCount = state.anchors.filter(anchor => displayState(anchor) === 'live' || displayState(anchor) === 'recording').length;
  const recordingCount = state.anchors.filter(anchor => displayState(anchor) === 'recording').length;
  const logEvent = (line: string) => {
    if (line.includes('准备开始录制')) return { type:'recording', label:'开始录制', color:'red', icon:<Video size={16}/> };
    if (line.includes('直播录制完成')) return { type:'completed', label:'录制完成', color:'green', icon:<FileCheck2 size={16}/> };
    if (line.includes('正在直播中')) return { type:'live', label:'检测开播', color:'teal', icon:<Radio size={16}/> };
    if (/错误|失败|异常|Error|Traceback/.test(line)) return { type:'error', label:'异常', color:'red', icon:<TriangleAlert size={16}/> };
    return { type:'system', label:'系统', color:'gray', icon:<Activity size={16}/> };
  };
  return <PageGrid>
    {state.storage?.level&&state.storage.level!=='healthy'&&<div className="wideColumn"><Alert color={state.storage.level==='critical'?'red':'yellow'} title={state.storage.level==='critical'?'磁盘空间已达到停止阈值':'磁盘空间不足'} icon={<TriangleAlert size={18}/>}>录像磁盘剩余 {state.storage.free_gb} GB；预警阈值 {state.storage.warning_gb} GB，停止阈值 {state.storage.stop_gb} GB。{state.storage.level==='critical'?' 系统会安全停止录制，释放空间后可重新启动。':' 建议清理已归档录像。'}</Alert></div>}
    <div className="wideColumn"><Panel title="录制总览" badge={<StatusBadge value={running ? recordingCount ? 'recording' : 'waiting' : 'stopped'} />} actions={<Group gap="xs"><Button size="xs" variant="subtle" leftSection={<Activity size={14}/>} onClick={()=>setLogsOpen(true)}>运行事件{logs.length ? ` · ${logs.length}` : ''}</Button><Button size="xs" leftSection={<Video size={15}/>} disabled={running || busy} loading={busy && !running} onClick={() => act(() => api('/api/start', { settings: state.settings }), '录制服务已启动')}>开始录制</Button><Button size="xs" color="red" variant="light" leftSection={<Square size={14}/>} disabled={!running || busy} loading={busy && running} onClick={() => act(() => api('/api/stop', {}), '录制已停止并保存')}>停止并保存</Button></Group>}>
      <div className="overviewRow"><div><Text fw={800} size="lg">{state.status?.auto_recovery?.recovering?'录制服务正在自动恢复':running ? recordingCount ? `正在录制 ${recordingCount} 位主播` : '监控运行中，等待主播开播' : '录制服务未启动'}</Text><Text c="dimmed" size="sm">{state.status?.auto_recovery?.recovering?`进程异常退出，正在进行第 ${state.status.auto_recovery.restart_attempts} 次恢复`:running ? '系统会持续巡检已启用主播，检测到开播后自动录制。' : '启动后会在后台自动巡检，不需要保持窗口打开。'}</Text></div><div className="recordingSummary"><div><strong>{state.anchors.filter(a => a.enabled_recording && anchorLiveUrl(a)).length}</strong><span>监控主播</span></div><div className="live"><strong>{activeCount}</strong><span>当前开播</span></div><div className="recording"><strong>{recordingCount}</strong><span>正在录制</span></div></div></div>
    </Panel></div>
    <div className="column">
      <Panel title="主播实时状态" badge={<Text c="dimmed" size="sm">每 4 秒刷新</Text>}>
        <div className="list roomStatusList">{state.anchors.length ? state.anchors.map(item => { const runtime=roomStates[item.id]; const status=displayState(item); return <div className={`listRow roomStatus ${status}`} key={item.id}>
          <Switch checked={item.enabled_recording !== false} disabled={running || busy || !anchorLiveUrl(item)} onChange={e => toggle(item, e.currentTarget.checked)} />
          <div className="grow"><Group gap="xs"><span className="roomStateDot"/><Text fw={700}>{item.name}</Text><StatusBadge value={status} /></Group><Text size="xs" c={status==='missed'?'red':'dimmed'} truncate>{runtime?.path ? `正在写入：${runtime.path}` : status === 'missed' ? '已检测到开播，但迟迟没有生成录像；系统仍会继续尝试' : status === 'waiting' ? '录制服务正在巡检，开播后会自动开始录制' : status === 'live' ? '已检测到开播，正在准备录制' : anchorLiveUrl(item) || '尚未解析直播间地址'}</Text>{runtime?.updated_at&&<Text size="xs" c="dimmed">状态更新：{new Date(runtime.updated_at*1000).toLocaleTimeString()}</Text>}</div>
          {status==='missed'&&<Button size="compact-xs" variant="light" loading={replayBusy==='check'} onClick={()=>checkReplay(item,runtime)}>检查回放</Button>}<Tooltip label={running ? '录制期间不可删除' : '删除'}><ActionIcon variant="subtle" color="red" disabled={running} onClick={() => remove(item)}><Trash2 size={17} /></ActionIcon></Tooltip>
        </div>}) : <Empty>添加直播间后即可巡检并自动录制</Empty>}</div>
        <Group className="addBar" wrap="nowrap"><TextInput value={room} onChange={e => setRoom(e.currentTarget.value)} onKeyDown={e => e.key === 'Enter' && addRoom()} placeholder="粘贴直播间地址，加入统一主播库" leftSection={<Plus size={16} />} flex={1} /><Button disabled={!room.trim()} onClick={addRoom}>添加</Button></Group>
      </Panel>
    </div>
    <div className="column">
      <Panel title="最近录像" badge={<Text c="dimmed" size="sm">{recordings.length} 场</Text>} actions={<Button size="xs" variant="subtle" leftSection={<FolderOpen size={15} />} onClick={() => api('/api/open-output', {}).catch(e => notify(e.message, true))}>打开目录</Button>}>
        <div className="list">{recordings.length ? recordings.slice(0, 12).map((group: any, index: number) => <div className="listRow" key={group.id || index}><div className="fileIcon"><Video size={18} /></div><div className="grow"><Text fw={650}>{group.name || group.anchor || '录像'}</Text><Text size="xs" c="dimmed">{group.segment_count || group.files?.length || 1} 个文件 · {formatBytes(group.total_size || group.size)} · {group.modified ? new Date(group.modified * 1000).toLocaleString() : ''}</Text></div></div>) : <Empty>还没有本地录像</Empty>}</div>
      </Panel>
    </div>
    <Drawer opened={logsOpen} onClose={()=>setLogsOpen(false)} position="right" size="lg" title="录制运行事件" overlayProps={{backgroundOpacity:.2,blur:2}}><Group justify="space-between" mb="md"><Text size="sm" c="dimmed">默认只展示开播、录制、完成和异常等关键节点</Text><Group gap="xs"><Button size="xs" variant="light" onClick={() => setDetailed(!detailed)}>{detailed ? '只看关键事件' : '显示全部日志'}</Button><Button size="xs" variant="subtle" onClick={clearLogs}>清空当前显示</Button></Group></Group><div className="eventTimeline">{logs.length ? logs.map((line,index)=>{const event=logEvent(line);return <div className={`logEvent ${event.type}`} key={`${index}-${line}`}><div className="logEventIcon">{event.icon}</div><div className="grow"><Group gap="xs"><Badge size="sm" variant="light" color={event.color}>{event.label}</Badge></Group><Text size="sm" mt={5}>{line}</Text></div></div>}) : <Empty>录制服务产生关键事件后会显示在这里</Empty>}</div></Drawer>
    <Drawer opened={replayOpen} onClose={()=>setReplayOpen(false)} position="right" size="md" title="直播回放补录"><Text size="sm" c="dimmed" mb="md">这里只展示平台明确标记或标题注明为直播回放的内容，下载前需要你确认。</Text>{replayCandidates.length?<div className="list">{replayCandidates.map(candidate=><div className="listRow" key={candidate.id}><div className="grow"><Text fw={700}>{candidate.desc||'直播回放'}</Text><Text size="xs" c="dimmed">{candidate.created_at?new Date(candidate.created_at*1000).toLocaleString():''} · {candidate.reason}</Text></div><Button size="xs" loading={replayBusy===candidate.id} onClick={async()=>{setReplayBusy(candidate.id);try{await api('/api/replays/download',{candidate_id:candidate.id});notify('直播回放已补录到媒体库')}catch(e){notify((e as Error).message,true)}finally{setReplayBusy('')}}}>确认补录</Button></div>)}</div>:<Empty>没有发现公开的直播回放；平台可能尚未生成回放或主播未公开。</Empty>}</Drawer>
  </PageGrid>;
}
