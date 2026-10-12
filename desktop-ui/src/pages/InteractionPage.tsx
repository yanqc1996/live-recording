import { ActionIcon, Button, Group, Select, Switch, Text, TextInput } from '@mantine/core';
import { Headphones, MessageCircle, Play, Radio, Send, Square, Trash2 } from 'lucide-react';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { api, audioStreamUrl } from '../api';
import { Empty, PageGrid, Panel, anchorLiveUrl } from '../components';
import type { AppState } from '../types';

export function InteractionPage({ state, refresh, notify }: { state: AppState; refresh: () => Promise<void>; notify: (m: string, e?: boolean) => void }) {
  const available = state.anchors.filter(anchor => !!anchorLiveUrl(anchor));
  const savedId = localStorage.getItem('liveRecorderSelectedAnchor');
  const [anchorId, setAnchorId] = useState(savedId && available.some(anchor => anchor.id === savedId) ? savedId : available[0]?.id || '');
  const selectedAnchor = state.anchors.find(anchor => anchor.id === anchorId);
  const room = anchorLiveUrl(selectedAnchor);
  const [resolveValue, setResolveValue] = useState(''); const [message, setMessage] = useState(''); const [events, setEvents] = useState<any[]>([]); const [cursor, setCursor] = useState(0); const [audio, setAudio] = useState(''); const [rank, setRank] = useState<any[]>([]); const [workMode, setWorkMode] = useState(localStorage.getItem('liveRecorderWorkMode') === '1');
  const feed = useRef<HTMLDivElement>(null); const listening = !!state.interaction?.listening;
  useEffect(() => { const poll = async () => { try { const data = await api<any>(`/api/interaction/events?cursor=${cursor}`); if (data.events?.length) setEvents(v => [...v, ...data.events].slice(-800)); setCursor(data.cursor || 0); } catch {} }; poll(); const timer = setInterval(poll, 1000); return () => clearInterval(timer); }, [cursor]);
  useEffect(() => { if (feed.current) feed.current.scrollTop = feed.current.scrollHeight; }, [events]);
  const act = async (fn: () => Promise<any>, success?: string) => { try { const data = await fn(); await refresh(); if (success) notify(success); return data; } catch (e) { notify((e as Error).message, true); } };
  const resolve = () => act(async () => { const data = await api<any>('/api/douyin/resolve-live-room', { url: resolveValue }); return data; }, '直播间已解析，可在主播库中保存');
  const send = async (e: FormEvent) => { e.preventDefault(); await act(() => api('/api/interaction/send', { content: message }), '弹幕已提交'); setMessage(''); };
  const loadAudio = async () => { const data = await act(() => api<any>('/api/interaction/audio-source', { room_url: room, quality: state.settings.quality || '原画' })); if (data?.audio?.stream_id) setAudio(audioStreamUrl(data.audio.stream_id)); };
  return <PageGrid>
    <div className="column">
      <Panel title="直播间控制" badge={<Text size="sm" c={listening ? 'green' : 'dimmed'}>{listening ? '监听中' : '未监听'}</Text>}>
        <TextInput label="直播间 / 用户主页 / 分享文本" value={resolveValue} onChange={e => setResolveValue(e.currentTarget.value)} rightSection={<ActionIcon variant="subtle" onClick={resolve}><SearchIcon /></ActionIcon>} />
        <Select mt="md" label="选择主播" value={anchorId} onChange={value => { setAnchorId(value || ''); localStorage.setItem('liveRecorderSelectedAnchor', value || ''); }} data={available.map(anchor => ({ value: anchor.id, label: anchor.name }))} searchable nothingFoundMessage="主播库中没有可用直播间" />
        <Group mt="md"><Button leftSection={<Play size={16} />} disabled={listening || !room} onClick={() => act(() => api('/api/interaction/start', { room_url: room }), '弹幕监听已连接')}>开始监听</Button><Button color="red" variant="light" leftSection={<Square size={15} />} disabled={!listening} onClick={() => act(() => api('/api/interaction/stop', {}), '监听已停止')}>停止</Button><Switch checked={workMode} label="工作模式" onChange={e => { setWorkMode(e.currentTarget.checked); localStorage.setItem('liveRecorderWorkMode', e.currentTarget.checked ? '1' : '0'); }} /></Group>
      </Panel>
      <Panel title="只听直播声音" badge={<Headphones size={17} />}>
        <Group mb="sm"><Button variant="light" onClick={loadAudio}>获取音频源</Button><Button variant="subtle" onClick={() => { setAudio(''); api('/api/interaction/audio-stop', {}).catch(() => {}); }}>停止声音</Button></Group>{audio ? <audio className="audio" src={audio} controls autoPlay /> : <Text c="dimmed" size="sm">获取后会在本机转码并播放，断线时可重新获取。</Text>}
      </Panel>
      {!workMode && <Panel title="礼物贡献榜" actions={<Button size="xs" variant="subtle" onClick={async () => { const data = await act(() => api<any>('/api/interaction/gift-rank', { room_url: room })); setRank(data?.gift_rank?.users || data?.gift_rank?.ranks || []); }}>刷新榜单</Button>}>
        {rank.length ? rank.map((item, i) => <div className="listRow" key={item.user?.id || i}><Text fw={800} w={24}>{i + 1}</Text><div className="grow"><Text>{item.user?.nickname || item.nickname || '匿名用户'}</Text><Text size="xs" c="dimmed">{item.score || item.value || ''}</Text></div></div>) : <Empty>刷新后显示当前贡献榜</Empty>}
      </Panel>}
    </div>
    <div className="column">
      <Panel title={workMode ? '实时消息' : '实时弹幕与用户'} badge={<Group gap={5}><Radio size={14} /><Text size="sm">{events.length}</Text></Group>} actions={<Button size="xs" variant="subtle" leftSection={<Trash2 size={13} />} onClick={() => setEvents([])}>清空</Button>}>
        <div className={`chatFeed ${workMode ? 'work' : ''}`} ref={feed}>{events.length ? events.filter(e => !workMode || ['chat','error','system'].includes(e.type)).map((event, index) => <div className={`event ${event.type}`} key={`${event.time}-${index}`}><Text size="xs" c="dimmed">{event.user?.nickname || ({ chat:'弹幕',gift:'礼物',follow:'关注',system:'系统',error:'异常' } as any)[event.type] || event.type}</Text><Text>{event.content || event.message}</Text></div>) : <Empty>选择直播间并开始监听</Empty>}</div>
        <form onSubmit={send}><Group className="sendBar" wrap="nowrap"><TextInput flex={1} value={message} onChange={e => setMessage(e.currentTarget.value)} placeholder="发送直播间弹幕" leftSection={<MessageCircle size={15} />} /><Button type="submit" leftSection={<Send size={15} />}>发送</Button></Group></form>
      </Panel>
    </div>
  </PageGrid>;
}
function SearchIcon(){ return <span style={{fontSize:14}}>解析</span> }
