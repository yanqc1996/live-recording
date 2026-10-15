import { Badge, Button, Group, NumberInput, Select, SimpleGrid, Switch, Text, TextInput } from '@mantine/core';
import { Gift, Headphones, MessageCircle, Play, Radio, Send, Square, Trash2, Waves } from 'lucide-react';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { Empty, PageGrid, Panel, anchorLiveUrl } from '../components';
import type { AppState } from '../types';

export function InteractionPage({ state, refresh, notify, activeAnchorId, setActiveAnchorId, events, clearEvents, audioAnchorId, audioPlaying, startAudio, stopAudio }: { state: AppState; refresh: () => Promise<void>; notify: (m: string, e?: boolean) => void; activeAnchorId: string; setActiveAnchorId: (value: string) => void; events: any[]; clearEvents: () => void; audioAnchorId: string; audioPlaying: boolean; startAudio: (anchorId?: string) => Promise<void>; stopAudio: () => Promise<void> }) {
  const available = state.anchors.filter(anchor => !!anchorLiveUrl(anchor));
  const selectedAnchor = state.anchors.find(anchor => anchor.id === activeAnchorId);
  const room = anchorLiveUrl(selectedAnchor);
  const [message, setMessage] = useState(''); const [rank, setRank] = useState<any[]>([]); const [workMode, setWorkMode] = useState(localStorage.getItem('liveRecorderWorkMode') === '1');
  const [giftPrices, setGiftPrices] = useState<Record<string, number | string>>({});
  const feed = useRef<HTMLDivElement>(null); const listening = !!state.interaction?.listening;
  useEffect(() => { if (feed.current) feed.current.scrollTop = feed.current.scrollHeight; }, [events]);
  const act = async (fn: () => Promise<any>, success?: string) => { try { const data = await fn(); await refresh(); if (success) notify(success); return data; } catch (e) { notify((e as Error).message, true); } };
  const send = async (e: FormEvent) => { e.preventDefault(); await act(() => api('/api/interaction/send', { content: message }), '弹幕已提交'); setMessage(''); };
  const playingAnchor = state.anchors.find(anchor => anchor.id === audioAnchorId);
  const gifts = state.gifts || {}; const giftItems = (gifts.gifts || []) as any[];
  const saveGiftPrice = async (item: any) => {
    const key = String(item.gift_id || item.name); const value = Number(giftPrices[key] ?? item.unit_value ?? 0);
    await act(() => api('/api/gifts/price', { gift_id: item.gift_id, gift_name: item.name, value }), '礼物音浪已更新');
  };
  return <PageGrid>
    <div className="column">
      <Panel title="直播间控制" badge={<Text size="sm" c={listening ? 'green' : 'dimmed'}>{listening ? '监听中' : '未监听'}</Text>}>
        <Select label="选择主播" description="直播地址、监听、声音和作品拉取共用当前主播" value={activeAnchorId} onChange={value => setActiveAnchorId(value || '')} data={available.map(anchor => ({ value: anchor.id, label: anchor.name }))} searchable nothingFoundMessage="主播库中没有可用直播间" />
        <Group mt="md"><Button leftSection={<Play size={16} />} disabled={listening || !room} onClick={() => act(() => api('/api/interaction/start', { anchor_id: activeAnchorId }), '弹幕监听已连接')}>开始监听</Button><Button color="red" variant="light" leftSection={<Square size={15} />} disabled={!listening} onClick={() => act(() => api('/api/interaction/stop', {}), '监听已停止')}>停止</Button><Switch checked={workMode} label="工作模式" onChange={e => { setWorkMode(e.currentTarget.checked); localStorage.setItem('liveRecorderWorkMode', e.currentTarget.checked ? '1' : '0'); }} /></Group>
      </Panel>
      <Panel title="只听直播声音" badge={<Headphones size={17} />}>
        <Group mb="sm"><Button variant="light" disabled={!activeAnchorId || (audioPlaying && audioAnchorId === activeAnchorId)} onClick={() => startAudio(activeAnchorId)}>{audioPlaying && audioAnchorId !== activeAnchorId ? '切换到当前主播' : '播放声音'}</Button><Button variant="subtle" disabled={!audioPlaying} onClick={() => stopAudio().catch(e => notify((e as Error).message, true))}>停止声音</Button></Group><Text c={audioPlaying ? 'green' : 'dimmed'} size="sm">{audioPlaying ? `正在播放：${playingAnchor?.name || '直播声音'}；切换到其他页面会继续播放。` : '声音会在全局播放器中播放，切换页面不会中断。'}</Text>
      </Panel>
      <Panel title="本场礼物与音浪" badge={<Group gap={5}><Gift size={15} /><Text size="sm">{gifts.gift_count || 0}</Text></Group>}>
        <SimpleGrid cols={3} spacing="sm">
          <div className="stat"><Text size="xl" fw={850}>{gifts.gift_count || 0}</Text><Text size="xs" c="dimmed">礼物数量</Text></div>
          <div className="stat"><Text size="xl" fw={850}>{gifts.sound_wave || 0}</Text><Text size="xs" c="dimmed">预估音浪</Text></div>
          <div className="stat"><Text size="xl" fw={850}>{gifts.donor_count || 0}</Text><Text size="xs" c="dimmed">送礼用户</Text></div>
        </SimpleGrid>
        {gifts.unknown_count > 0 && <Text size="xs" c="orange" mt="sm">有 {gifts.unknown_count} 个礼物尚无价值数据，可在下方补充单个礼物的音浪。</Text>}
        <Group gap="xs" mt="sm"><Badge color="green" variant="light">平台值 {gifts.platform_count || 0}</Badge>{gifts.rank_sound_wave>0&&<Badge color="violet" variant="light">榜单补充 {gifts.rank_sound_wave} 音浪</Badge>}<Badge color="blue" variant="light">本地估算 {gifts.estimated_count || 0}</Badge><Badge color={gifts.unknown_count ? 'orange' : 'gray'} variant="light">未知 {gifts.unknown_count || 0}</Badge><Text size="xs" c="dimmed">价值覆盖率 {gifts.coverage_percent || 0}%</Text></Group>
        {!workMode && <div className="list" style={{marginTop: 10}}>{giftItems.length ? giftItems.map(item => { const key=String(item.gift_id||item.name); return <div className="listRow" key={key}><div className="grow"><Group gap="xs"><Text fw={750}>{item.name}</Text><Badge size="sm" variant="light">× {item.quantity}</Badge></Group><Text size="xs" c="dimmed">合计 {item.sound_wave || 0} 音浪{item.value_known ? '' : ' · 待补充价值'}</Text></div><NumberInput w={112} size="xs" min={0} allowDecimal={false} value={giftPrices[key] ?? item.unit_value ?? 0} onChange={value=>setGiftPrices(current=>({...current,[key]:value}))} leftSection={<Waves size={13}/>} onBlur={()=>saveGiftPrice(item)} aria-label={`${item.name}单个音浪`} /></div> }) : <Empty>开始监听后，礼物流水会按主播和本场直播保存</Empty>}</div>}
        <Text size="xs" c="dimmed" mt="sm">音浪优先采用直播礼物消息；匿名数据流未下发礼物时，每 30 秒读取贡献榜增量补充音浪。贡献榜只能提供用户与音浪，无法还原具体礼物名称。</Text>
      </Panel>
      {!workMode && <Panel title="本场实时贡献榜" badge={<Text size="sm" c="dimmed">{(gifts.users || []).length} 人</Text>}>
        {(gifts.users || []).length ? (gifts.users || []).slice(0, 10).map((item:any,index:number)=><div className="listRow" key={item.id||item.nickname}><Text fw={850} w={26}>{index+1}</Text><div className="grow"><Text fw={700}>{item.nickname}</Text><Text size="xs" c="dimmed">{item.quantity} 件礼物</Text></div><Text fw={800}>{item.sound_wave || 0} 音浪</Text></div>) : <Empty>收到礼物后自动生成本场排行</Empty>}
      </Panel>}
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
