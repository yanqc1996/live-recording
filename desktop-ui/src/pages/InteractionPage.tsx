import { Badge, Button, Group, NumberInput, Select, SimpleGrid, Switch, Text, TextInput } from '@mantine/core';
import { CheckCircle2, Circle, Code2, Cpu, FileCode2, Folder, Gift, GitBranch, Headphones, MessageCircle, Play, Radio, Send, Server, Square, Terminal, Trash2, Waves, XCircle } from 'lucide-react';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { Empty, PageGrid, Panel, anchorLiveUrl } from '../components';
import type { AppState } from '../types';
import { AnchorPicker } from '../AnchorPicker';

export function InteractionPage({ state, refresh, notify, activeAnchorId, setActiveAnchorId, events, clearEvents, audioAnchorId, audioPlaying, startAudio, stopAudio, workMode, setWorkMode }: { state: AppState; refresh: () => Promise<void>; notify: (m: string, e?: boolean) => void; activeAnchorId: string; setActiveAnchorId: (value: string) => void; events: any[]; clearEvents: () => void; audioAnchorId: string; audioPlaying: boolean; startAudio: (anchorId?: string) => Promise<void>; stopAudio: () => Promise<void>; workMode: boolean; setWorkMode: (value: boolean) => void }) {
  const available = state.anchors.filter(anchor => !!anchorLiveUrl(anchor));
  const selectedAnchor = state.anchors.find(anchor => anchor.id === activeAnchorId);
  const room = anchorLiveUrl(selectedAnchor);
  const [message, setMessage] = useState(''); const [rank, setRank] = useState<any[]>([]); const [sending, setSending] = useState(false);
  const [giftPrices, setGiftPrices] = useState<Record<string, number | string>>({});
  const feed = useRef<HTMLDivElement>(null); const listening = !!state.interaction?.listening;
  useEffect(() => { if (feed.current) feed.current.scrollTop = feed.current.scrollHeight; }, [events]);
  const act = async (fn: () => Promise<any>, success?: string) => { try { const data = await fn(); await refresh(); if (success) notify(success); return data; } catch (e) { notify((e as Error).message, true); } };
  const send = async (e: FormEvent) => {
    e.preventDefault();
    const content = message.trim();
    if (!content) { notify('请先输入弹幕内容', true); return; }
    if (!room) { notify('请先选择有直播间地址的主播', true); return; }
    if (sending) return;
    setSending(true);
    try {
      if (window.liveRecorderDesktop) {
        await window.liveRecorderDesktop.sendDouyinChatHidden(room, content);
      } else {
        await api('/api/interaction/send', { content });
      }
      setMessage('');
      notify('弹幕已发送');
      await refresh();
    } catch (e) {
      notify((e as Error).message || '弹幕发送失败', true);
    } finally {
      setSending(false);
    }
  };
  const playingAnchor = state.anchors.find(anchor => anchor.id === audioAnchorId);
  const gifts = state.gifts || {}; const giftItems = (gifts.gifts || []) as any[];
  const saveGiftPrice = async (item: any) => {
    const key = String(item.gift_id || item.name); const value = Number(giftPrices[key] ?? item.unit_value ?? 0);
    await act(() => api('/api/gifts/price', { gift_id: item.gift_id, gift_name: item.name, value }), '礼物音浪已更新');
  };
  return <PageGrid>
    <div className="column">
      <Panel title="直播间控制" badge={<Text size="sm" c={listening ? 'green' : 'dimmed'}>{listening ? '监听中' : '未监听'}</Text>}>
        <AnchorPicker state={state} value={activeAnchorId} onChange={setActiveAnchorId}/>
        <Group mt="md" justify="space-between"><Button variant={listening ? 'light' : 'filled'} color={listening ? 'red' : 'blue'} leftSection={listening ? <Square size={15}/> : <Play size={16}/>} disabled={!room && !listening} onClick={() => act(() => api(listening ? '/api/interaction/stop' : '/api/interaction/start', listening ? {} : { anchor_id: activeAnchorId }), listening ? '监听已停止' : '弹幕监听已连接')}>{listening ? '停止监听' : '开始监听'}</Button><Switch checked={workMode} label="工作模式" onChange={e => setWorkMode(e.currentTarget.checked)} /></Group>
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
        <form onSubmit={send}><Group className="sendBar" wrap="nowrap"><TextInput flex={1} value={message} maxLength={200} disabled={sending} onChange={e => setMessage(e.currentTarget.value)} placeholder="输入直播间弹幕" leftSection={<MessageCircle size={15} />} rightSection={<Text size="xs" c="dimmed">{message.length}/200</Text>} rightSectionWidth={58} /><Button type="submit" leftSection={<Send size={15} />} loading={sending} disabled={!room || !message.trim()}>发送</Button></Group></form>
        <Text size="xs" c="dimmed" mt="xs">发送使用已登录的抖音会话，在后台静音完成；失败时会保留输入内容便于重试。</Text>
      </Panel>
    </div>
  </PageGrid>;
}

function DeveloperWorkspace({ state, available, activeAnchorId, setActiveAnchorId, listening, room, events, feed, clearEvents, audioPlaying, audioAnchorId, startAudio, stopAudio, act, message, setMessage, send, exit }: any) {
  const selected = state.anchors.find((anchor:any) => anchor.id === activeAnchorId);
  const consoleEvents = events.filter((event:any) => ['chat','error','system'].includes(event.type)).slice(-120);
  const healthy = !!state.status?.running;
  const source = [
    ['01', "import { workspace } from './runtime';"], ['02', ''],
    ['03', 'const environment = {'], ['04', `  name: '${selected?.name || 'development'}',`],
    ['05', `  service: '${listening ? 'connected' : 'idle'}',`], ['06', `  audioWorker: ${audioPlaying ? 'true' : 'false'},`],
    ['07', `  recorder: '${healthy ? 'healthy' : 'stopped'}',`], ['08', '};'], ['09', ''],
    ['10', 'workspace.observe(environment);'], ['11', '// Background jobs are isolated from the editor session.'],
  ];
  return <div className="developerWorkspace">
    <div className="devTitlebar"><Group gap="xs"><Code2 size={17}/><Text fw={650} size="sm">workspace-control</Text><Text size="xs" c="dimmed">— Visual Studio Code</Text></Group><Group gap="xs"><span className={`devDot ${healthy?'ok':''}`}/><Text size="xs" c="dimmed">Local Runtime</Text><Switch size="xs" checked label="Work Mode" onChange={exit}/></Group></div>
    <div className="devBody">
      <aside className="devActivity"><FileCode2 size={21}/><Folder size={21}/><GitBranch size={21}/><Cpu size={21}/><div className="devActivityBottom"><Server size={20}/></div></aside>
      <aside className="devExplorer"><Text className="devSectionLabel">EXPLORER</Text><Text size="xs" fw={750} mt="sm">WORKSPACE-CONTROL</Text><div className="devTree"><div><Folder size={14}/> src</div><div className="nested active"><FileCode2 size={14}/> monitoring.ts</div><div className="nested"><FileCode2 size={14}/> runtime.ts</div><div><Folder size={14}/> services</div><div className="nested"><FileCode2 size={14}/> audio.worker.ts</div><div><Folder size={14}/> logs</div><div className="nested"><FileCode2 size={14}/> session.log</div></div><div className="devOutline"><Text className="devSectionLabel">OUTLINE</Text><Text size="xs" c="dimmed">environment</Text><Text size="xs" c="dimmed">workspace.observe()</Text></div></aside>
      <section className="devMain">
        <div className="devTabs"><div className="active"><FileCode2 size={14}/> monitoring.ts <span>×</span></div><div><FileCode2 size={14}/> runtime.ts</div></div>
        <div className="devToolbar"><Select size="xs" w={230} value={activeAnchorId} onChange={value=>setActiveAnchorId(value||'')} data={available.map((anchor:any)=>({value:anchor.id,label:`env / ${anchor.name}`}))}/><Button size="compact-xs" variant="subtle" leftSection={<Play size={13}/>} disabled={listening||!room} onClick={()=>act(()=>api('/api/interaction/start',{anchor_id:activeAnchorId}))}>Run Service</Button><Button size="compact-xs" variant="subtle" color="gray" leftSection={<Square size={12}/>} disabled={!listening} onClick={()=>act(()=>api('/api/interaction/stop',{}))}>Stop</Button><Button size="compact-xs" variant="subtle" leftSection={<Headphones size={13}/>} onClick={()=>audioPlaying?stopAudio():startAudio(activeAnchorId)}>{audioPlaying?'Stop Worker':'Start Worker'}</Button></div>
        <div className="devEditor">{source.map(([line,code])=><div className="codeLine" key={line}><span>{line}</span><code>{code}</code></div>)}</div>
        <div className="devTerminalHeader"><Group gap="md"><Text size="xs" fw={750}>TERMINAL</Text><Text size="xs" c="dimmed">OUTPUT</Text><Text size="xs" c="dimmed">PROBLEMS</Text></Group><Button size="compact-xs" variant="subtle" color="gray" leftSection={<Trash2 size={12}/>} onClick={clearEvents}>Clear</Button></div>
        <div className="devTerminal" ref={feed}>{consoleEvents.length?consoleEvents.map((event:any,index:number)=><div className={`terminalLine ${event.type}`} key={`${event.time}-${index}`}><span className="terminalTime">{new Date((event.time||0)*1000).toLocaleTimeString()}</span><span className="terminalLevel">{event.type==='error'?'ERROR':event.type==='chat'?'EVENT':'INFO'}</span><span>{event.content||event.message}</span></div>):<div className="terminalLine"><span className="terminalTime">--:--:--</span><span className="terminalLevel">INFO</span><span>Workspace ready. Run a service to stream events.</span></div>}</div>
        <form onSubmit={send} className="devCommand"><Terminal size={15}/><TextInput variant="unstyled" flex={1} value={message} onChange={e=>setMessage(e.currentTarget.value)} placeholder="Run command…"/><Button type="submit" size="compact-xs" variant="subtle">Execute</Button></form>
      </section>
      <aside className="devInspector"><Text className="devSectionLabel">SYSTEM HEALTH</Text><div className="healthItem">{healthy?<CheckCircle2 size={16}/>:<XCircle size={16}/>}<div><Text size="sm">Recorder</Text><Text size="xs" c="dimmed">{healthy?'Operational':'Stopped'}</Text></div></div><div className="healthItem">{listening?<CheckCircle2 size={16}/>:<Circle size={16}/>}<div><Text size="sm">Event service</Text><Text size="xs" c="dimmed">{listening?'Connected':'Idle'}</Text></div></div><div className="healthItem">{audioPlaying?<CheckCircle2 size={16}/>:<Circle size={16}/>}<div><Text size="sm">Audio worker</Text><Text size="xs" c="dimmed">{audioPlaying&&audioAnchorId===activeAnchorId?'Running':'Idle'}</Text></div></div><Text className="devSectionLabel" mt="xl">RUNTIME</Text><div className="devMetric"><span>Events</span><strong>{events.length}</strong></div><div className="devMetric"><span>Jobs</span><strong>{state.recording_tasks?.running||0}</strong></div><div className="devMetric"><span>Storage</span><strong>{state.storage?.free_gb||0} GB</strong></div></aside>
    </div>
    <div className="devStatusbar"><Group gap="md"><span><GitBranch size={12}/> main*</span><span>ⓧ 0&nbsp;&nbsp;△ 0</span></Group><Group gap="md"><span>UTF-8</span><span>TypeScript React</span><span>Ln 10, Col 31</span></Group></div>
  </div>;
}
