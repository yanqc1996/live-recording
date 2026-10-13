import { Button, Group, Select, Switch, Text, TextInput } from '@mantine/core';
import { Headphones, MessageCircle, Play, Radio, Send, Square, Trash2 } from 'lucide-react';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { Empty, PageGrid, Panel, anchorLiveUrl } from '../components';
import type { AppState } from '../types';

export function InteractionPage({ state, refresh, notify, activeAnchorId, setActiveAnchorId, events, clearEvents, audioAnchorId, audioPlaying, startAudio, stopAudio }: { state: AppState; refresh: () => Promise<void>; notify: (m: string, e?: boolean) => void; activeAnchorId: string; setActiveAnchorId: (value: string) => void; events: any[]; clearEvents: () => void; audioAnchorId: string; audioPlaying: boolean; startAudio: (anchorId?: string) => Promise<void>; stopAudio: () => Promise<void> }) {
  const available = state.anchors.filter(anchor => !!anchorLiveUrl(anchor));
  const selectedAnchor = state.anchors.find(anchor => anchor.id === activeAnchorId);
  const room = anchorLiveUrl(selectedAnchor);
  const [message, setMessage] = useState(''); const [rank, setRank] = useState<any[]>([]); const [workMode, setWorkMode] = useState(localStorage.getItem('liveRecorderWorkMode') === '1');
  const feed = useRef<HTMLDivElement>(null); const listening = !!state.interaction?.listening;
  useEffect(() => { if (feed.current) feed.current.scrollTop = feed.current.scrollHeight; }, [events]);
  const act = async (fn: () => Promise<any>, success?: string) => { try { const data = await fn(); await refresh(); if (success) notify(success); return data; } catch (e) { notify((e as Error).message, true); } };
  const send = async (e: FormEvent) => { e.preventDefault(); await act(() => api('/api/interaction/send', { content: message }), '弹幕已提交'); setMessage(''); };
  const playingAnchor = state.anchors.find(anchor => anchor.id === audioAnchorId);
  return <PageGrid>
    <div className="column">
      <Panel title="直播间控制" badge={<Text size="sm" c={listening ? 'green' : 'dimmed'}>{listening ? '监听中' : '未监听'}</Text>}>
        <Select label="选择主播" description="直播地址、监听、声音和作品拉取共用当前主播" value={activeAnchorId} onChange={value => setActiveAnchorId(value || '')} data={available.map(anchor => ({ value: anchor.id, label: anchor.name }))} searchable nothingFoundMessage="主播库中没有可用直播间" />
        <Group mt="md"><Button leftSection={<Play size={16} />} disabled={listening || !room} onClick={() => act(() => api('/api/interaction/start', { anchor_id: activeAnchorId }), '弹幕监听已连接')}>开始监听</Button><Button color="red" variant="light" leftSection={<Square size={15} />} disabled={!listening} onClick={() => act(() => api('/api/interaction/stop', {}), '监听已停止')}>停止</Button><Switch checked={workMode} label="工作模式" onChange={e => { setWorkMode(e.currentTarget.checked); localStorage.setItem('liveRecorderWorkMode', e.currentTarget.checked ? '1' : '0'); }} /></Group>
      </Panel>
      <Panel title="只听直播声音" badge={<Headphones size={17} />}>
        <Group mb="sm"><Button variant="light" disabled={!activeAnchorId || (audioPlaying && audioAnchorId === activeAnchorId)} onClick={() => startAudio(activeAnchorId)}>{audioPlaying && audioAnchorId !== activeAnchorId ? '切换到当前主播' : '播放声音'}</Button><Button variant="subtle" disabled={!audioPlaying} onClick={() => stopAudio().catch(e => notify((e as Error).message, true))}>停止声音</Button></Group><Text c={audioPlaying ? 'green' : 'dimmed'} size="sm">{audioPlaying ? `正在播放：${playingAnchor?.name || '直播声音'}；切换到其他页面会继续播放。` : '声音会在全局播放器中播放，切换页面不会中断。'}</Text>
      </Panel>
      {!workMode && <Panel title="礼物贡献榜" actions={<Button size="xs" variant="subtle" onClick={async () => { const data = await act(() => api<any>('/api/interaction/gift-rank', { anchor_id: activeAnchorId })); setRank(data?.gift_rank?.users || data?.gift_rank?.ranks || []); }}>刷新榜单</Button>}>
        {rank.length ? rank.map((item, i) => <div className="listRow" key={item.user?.id || i}><Text fw={800} w={24}>{i + 1}</Text><div className="grow"><Text>{item.user?.nickname || item.nickname || '匿名用户'}</Text><Text size="xs" c="dimmed">{item.score || item.value || ''}</Text></div></div>) : <Empty>刷新后显示当前贡献榜</Empty>}
      </Panel>}
    </div>
    <div className="column">
      <Panel title={workMode ? '实时消息' : '实时弹幕与用户'} badge={<Group gap={5}><Radio size={14} /><Text size="sm">{events.length}</Text></Group>} actions={<Button size="xs" variant="subtle" leftSection={<Trash2 size={13} />} onClick={clearEvents}>清空</Button>}>
        <div className={`chatFeed ${workMode ? 'work' : ''}`} ref={feed}>{events.length ? events.filter(e => !workMode || ['chat','error','system'].includes(e.type)).map((event, index) => <div className={`event ${event.type}`} key={`${event.time}-${index}`}><Text size="xs" c="dimmed">{event.user?.nickname || ({ chat:'弹幕',gift:'礼物',follow:'关注',system:'系统',error:'异常' } as any)[event.type] || event.type}</Text><Text>{event.content || event.message}</Text></div>) : <Empty>选择直播间并开始监听</Empty>}</div>
        <form onSubmit={send}><Group className="sendBar" wrap="nowrap"><TextInput flex={1} value={message} onChange={e => setMessage(e.currentTarget.value)} placeholder="发送直播间弹幕" leftSection={<MessageCircle size={15} />} /><Button type="submit" leftSection={<Send size={15} />}>发送</Button></Group></form>
      </Panel>
    </div>
  </PageGrid>;
}
