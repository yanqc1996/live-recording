import { Badge, Button, Group, Select, Text, TextInput, Textarea } from '@mantine/core';
import { Radio, RefreshCw, Search, UserPlus } from 'lucide-react';
import { useMemo, useState } from 'react';
import { api } from '../api';
import { Empty, FieldGrid, PageGrid, Panel, StatusBadge } from '../components';
import type { Anchor, AppState } from '../types';

export function AnchorsPage({ state, refresh, notify, navigate }: { state: AppState; refresh: () => Promise<void>; notify: (m: string, e?: boolean) => void; navigate: (page: string) => void }) {
  const [selectedId, setSelectedId] = useState<string>();
  const [query, setQuery] = useState(''); const [status, setStatus] = useState<string | null>('all');
  const [discover, setDiscover] = useState(''); const [results, setResults] = useState<any[]>([]); const [searching, setSearching] = useState(false);
  const [name, setName] = useState(''); const [profile, setProfile] = useState(''); const [live, setLive] = useState('');
  const selected = state.anchors.find(a => a.id === selectedId);
  const filtered = useMemo(() => state.anchors.filter(a => (status === 'all' || (a.last_live_status || 'unknown') === status) && (!query || [a.name, a.profile_url, a.live_url].some(v => String(v || '').toLowerCase().includes(query.toLowerCase())))), [state.anchors, query, status]);
  const run = async (fn: () => Promise<any>, message: string) => { try { await fn(); await refresh(); notify(message); } catch (e) { notify((e as Error).message, true); } };
  const search = async () => { if (!discover.trim()) return notify('请输入主播昵称或抖音号', true); setSearching(true); try { const data = await api<any>('/api/anchors/search', { keyword: discover, limit: 12 }); setResults(data.users || []); if (!data.users?.length) notify('没有找到匹配主播'); } catch (e) { notify((e as Error).message, true); } finally { setSearching(false); } };
  const add = (payload = { name, profile_url: profile, live_url: live }) => run(async () => { await api('/api/anchors', payload); setName(''); setProfile(''); setLive(''); }, `已添加 ${payload.name || '主播'}`);
  return <PageGrid>
    <div className="column">
      <Panel title="发现主播" badge={<Badge variant="light">昵称 / 抖音号</Badge>}>
        <Group wrap="nowrap"><TextInput flex={1} value={discover} onChange={e => setDiscover(e.currentTarget.value)} onKeyDown={e => e.key === 'Enter' && search()} leftSection={<Search size={16} />} placeholder="输入主播昵称或抖音号" /><Button loading={searching} onClick={search}>搜索</Button></Group>
        <Text size="xs" c="dimmed" mt="sm">请核对抖音号后加入；搜索受限时，可粘贴手机端分享文本。</Text>
        {!!results.length && <div className="searchResults">{results.map((user, index) => { const exists = state.anchors.some(a => a.profile_url === user.profile_url); return <div className="candidate" key={user.sec_user_id || index}><div className="avatar">{String(user.nickname || '主').slice(0, 1)}</div><div className="grow"><Text fw={700}>{user.nickname}</Text><Text size="xs" c="dimmed">{user.display_id ? `抖音号 ${user.display_id}` : '未公开抖音号'}{user.follower_count != null ? ` · ${Number(user.follower_count).toLocaleString()} 粉丝` : ''}{user.is_live ? ' · 正在直播' : ''}</Text><Text size="xs" c="dimmed" truncate>{user.signature}</Text></div><Button size="xs" variant={exists ? 'subtle' : 'light'} disabled={exists} onClick={() => add({ name: user.nickname, profile_url: user.profile_url, live_url: '' })}>{exists ? '已在库中' : '加入主播库'}</Button></div> })}</div>}
      </Panel>
      <Panel title="主播库" badge={<Text c="dimmed" size="sm">{filtered.length} / {state.anchors.length}</Text>} actions={<Button size="xs" variant="subtle" leftSection={<RefreshCw size={14} />} onClick={() => run(() => api('/api/anchors/check-live', {}), '巡检完成')}>巡检全部</Button>}>
        <Group mb="sm" wrap="nowrap"><TextInput flex={1} value={query} onChange={e => setQuery(e.currentTarget.value)} placeholder="筛选已保存主播" /><Select w={130} value={status} onChange={setStatus} data={[['all','全部状态'],['live','直播中'],['offline','未开播'],['error','异常'],['unknown','未巡检']].map(([value,label])=>({value,label}))} /></Group>
        <div className="list">{filtered.length ? filtered.map(anchor => <button className={`anchorItem ${selectedId === anchor.id ? 'active' : ''}`} key={anchor.id} onClick={() => setSelectedId(anchor.id)}><div className="grow"><Text fw={700}>{anchor.name}</Text><Text size="xs" c="dimmed" truncate>{anchor.profile_url}</Text></div><StatusBadge value={anchor.last_live_status} /></button>) : <Empty>没有符合条件的主播</Empty>}</div>
      </Panel>
    </div>
    <div className="column">
      <Panel title={selected?.name || '主播资料'} badge={selected ? <StatusBadge value={selected.last_live_status} /> : undefined}>
        {selected ? <AnchorEditor anchor={selected} run={run} notify={notify} navigate={navigate} /> : <Empty>从左侧选择主播后可视化编辑和操作</Empty>}
      </Panel>
      <Panel title="手动添加" badge={<UserPlus size={17} />}>
        <FieldGrid><TextInput label="主播名称（可选）" value={name} onChange={e => setName(e.currentTarget.value)} /><TextInput className="wide" label="主页 / 分享 / 直播间地址" value={profile} onChange={e => setProfile(e.currentTarget.value)} /><TextInput className="wide" label="备用直播间地址（可选）" value={live} onChange={e => setLive(e.currentTarget.value)} /></FieldGrid><Button mt="md" onClick={() => add()}>添加主播</Button>
      </Panel>
    </div>
  </PageGrid>;
}

function AnchorEditor({ anchor, run, notify, navigate }: { anchor: Anchor; run: (fn: () => Promise<any>, m: string) => void; notify: (m: string, e?: boolean) => void; navigate: (p: string) => void }) {
  const [name, setName] = useState(anchor.name); const [profile, setProfile] = useState(anchor.profile_url); const [live, setLive] = useState(anchor.live_url); const [quality, setQuality] = useState(anchor.default_quality || '原画');
  const save = () => run(() => api(`/api/anchors/${anchor.id}`, { name, profile_url: profile, live_url: live, default_quality: quality, enabled_recording: anchor.enabled_recording !== false }), '主播资料已保存');
  return <><FieldGrid><TextInput label="主播名称" value={name} onChange={e => setName(e.currentTarget.value)} /><Select label="默认画质" value={quality} onChange={v => setQuality(v || '原画')} data={['原画','超清','高清','标清','流畅']} /><Textarea className="wide" label="主页 / 分享链接" value={profile} onChange={e => setProfile(e.currentTarget.value)} autosize /><TextInput className="wide" label="直播间地址" value={live} onChange={e => setLive(e.currentTarget.value)} /></FieldGrid><Group mt="md"><Button onClick={save}>保存修改</Button><Button variant="light" onClick={() => run(() => api(`/api/anchors/${anchor.id}/resolve`, {}), '直播间已解析')}>重新解析</Button><Button variant="light" leftSection={<Radio size={15} />} onClick={() => run(() => api(`/api/anchors/${anchor.id}/use-recording`, {}), '已加入录制列表')}>加入录制</Button><Button variant="subtle" disabled={!anchor.live_url} onClick={() => { localStorage.setItem('liveRecorderSelectedRoom', anchor.live_url); navigate('interact'); }}>用于监听</Button><Button variant="subtle" color="red" onClick={() => confirm('确定删除这个主播吗？') && run(() => api(`/api/anchors/${anchor.id}`, undefined, 'DELETE'), '主播已删除')}>删除</Button></Group>{anchor.last_check_error && <Text c="red" size="sm" mt="sm">{anchor.last_check_error}</Text>}</>;
}
