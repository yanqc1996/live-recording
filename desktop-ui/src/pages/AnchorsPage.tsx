import { Accordion, Badge, Button, Group, Select, Switch, Table, Text, TextInput, Textarea } from '@mantine/core';
import { CheckCircle2, Database, FolderOpen, Link2, Radio, RefreshCw, Search, Sheet, UserPlus } from 'lucide-react';
import { useMemo, useState } from 'react';
import { api } from '../api';
import { Empty, FieldGrid, PageGrid, Panel, StatusBadge } from '../components';
import type { Anchor, AppState } from '../types';

export function AnchorsPage({ state, refresh, notify, navigate, activeAnchorId, setActiveAnchorId }: { state: AppState; refresh: () => Promise<void>; notify: (m: string, e?: boolean) => void; navigate: (page: string) => void; activeAnchorId: string; setActiveAnchorId: (value: string) => void }) {
  const [query, setQuery] = useState(''); const [status, setStatus] = useState<string | null>('all');
  const [discover, setDiscover] = useState(''); const [results, setResults] = useState<any[]>([]); const [searching, setSearching] = useState(false);
  const [name, setName] = useState(''); const [profile, setProfile] = useState(''); const [live, setLive] = useState('');
  const [preview, setPreview] = useState<any>(); const [resolving, setResolving] = useState(false);
  const [collectionMode, setCollectionMode] = useState(false);
  const selected = state.anchors.find(a => a.id === activeAnchorId);
  const filtered = useMemo(() => state.anchors.filter(a => (status === 'all' || (a.last_live_status || 'unknown') === status) && (!query || [a.name, a.profile_url, a.live_url].some(v => String(v || '').toLowerCase().includes(query.toLowerCase())))), [state.anchors, query, status]);
  const run = async (fn: () => Promise<any>, message: string) => { try { await fn(); await refresh(); notify(message); } catch (e) { notify((e as Error).message, true); } };
  const search = async () => { if (!discover.trim()) return notify('请输入主播昵称或抖音号', true); setSearching(true); try { const data = await api<any>('/api/anchors/search', { keyword: discover, limit: 12 }); setResults(data.users || []); if (!data.users?.length) notify('没有找到匹配主播'); } catch (e) { notify((e as Error).message, true); } finally { setSearching(false); } };
  const add = (payload: Record<string, any> = { name, profile_url: profile, live_url: live }) => run(async () => { await api('/api/anchors', payload); setName(''); setProfile(''); setLive(''); setPreview(undefined); }, `已添加 ${payload.name || '主播'}`);
  const resolveShare = async () => {
    if (!profile.trim()) return notify('请粘贴手机端主页分享文案或链接', true);
    setResolving(true); setPreview(undefined);
    try {
      const data = await api<any>('/api/douyin/resolve-live-room', { url: profile });
      const result = data.live_room;
      setPreview(result);
      if (result.nickname) setName(result.nickname);
      if (result.room_url) setLive(result.room_url);
    } catch (e) { notify((e as Error).message, true); }
    finally { setResolving(false); }
  };
  const addResolved = () => {
    if (!preview) return add();
    add({ name: name || preview.nickname || '未命名主播', profile_url: preview.profile_url || preview.source_url || profile,
      live_url: preview.room_url || live, sec_user_id: preview.sec_anchor_id || '', web_rid: preview.web_rid || '', room_id: preview.room_id || '',
      last_live_status: preview.is_live ? 'live' : 'offline', last_resolved_at: Math.floor(Date.now() / 1000) });
  };
  if (collectionMode) return <CollectionEditor anchors={state.anchors} recording={!!state.status?.running} close={() => setCollectionMode(false)} refresh={refresh} notify={notify} />;
  return <PageGrid>
    <div className="column">
      <Panel title="发现主播" badge={<Badge variant="light">昵称 / 抖音号</Badge>}>
        <Group wrap="nowrap"><TextInput flex={1} value={discover} onChange={e => setDiscover(e.currentTarget.value)} onKeyDown={e => e.key === 'Enter' && search()} leftSection={<Search size={16} />} placeholder="输入主播昵称或抖音号" /><Button loading={searching} onClick={search}>搜索</Button></Group>
        <Text size="xs" c="dimmed" mt="sm">请核对抖音号后加入；搜索受限时，可粘贴手机端分享文本。</Text>
        {!!results.length && <div className="searchResults">{results.map((user, index) => { const exists = state.anchors.some(a => a.profile_url === user.profile_url); return <div className="candidate" key={user.sec_user_id || index}><div className="avatar">{String(user.nickname || '主').slice(0, 1)}</div><div className="grow"><Text fw={700}>{user.nickname}</Text><Text size="xs" c="dimmed">{user.display_id ? `抖音号 ${user.display_id}` : '未公开抖音号'}{user.follower_count != null ? ` · ${Number(user.follower_count).toLocaleString()} 粉丝` : ''}{user.is_live ? ' · 正在直播' : ''}</Text><Text size="xs" c="dimmed" truncate>{user.signature}</Text></div><Button size="xs" variant={exists ? 'subtle' : 'light'} disabled={exists} onClick={() => add({ name: user.nickname, profile_url: user.profile_url, live_url: '' })}>{exists ? '已在库中' : '加入主播库'}</Button></div> })}</div>}
      </Panel>
      <Panel title="主播库" badge={<Text c="dimmed" size="sm">{filtered.length} / {state.anchors.length}</Text>} actions={<Group gap="xs"><Button size="xs" variant="light" leftSection={<Sheet size={14} />} onClick={() => setCollectionMode(true)}>编辑集合</Button><Button size="xs" variant="subtle" leftSection={<RefreshCw size={14} />} onClick={() => run(() => api('/api/anchors/check-live', {}), '巡检完成')}>巡检全部</Button></Group>}>
        <Group mb="sm" wrap="nowrap"><TextInput flex={1} value={query} onChange={e => setQuery(e.currentTarget.value)} placeholder="筛选已保存主播" /><Select w={130} value={status} onChange={setStatus} data={[['all','全部状态'],['live','直播中'],['offline','未开播'],['error','异常'],['unknown','未巡检']].map(([value,label])=>({value,label}))} /></Group>
        <div className="list">{filtered.length ? filtered.map(anchor => <button className={`anchorItem ${activeAnchorId === anchor.id ? 'active' : ''}`} key={anchor.id} onClick={() => setActiveAnchorId(anchor.id)}><div className="grow"><Text fw={700}>{anchor.name}</Text><Text size="xs" c="dimmed" truncate>{anchor.profile_url}</Text></div><StatusBadge value={anchor.last_live_status} /></button>) : <Empty>没有符合条件的主播</Empty>}</div>
      </Panel>
    </div>
    <div className="column">
      <Panel title={selected ? `${selected.name} · 数据编辑器` : '主播数据编辑器'} badge={selected ? <StatusBadge value={selected.last_live_status} /> : undefined}>
        {selected ? <AnchorEditor key={selected.id} anchor={selected} run={run} notify={notify} navigate={navigate} setActiveAnchorId={setActiveAnchorId} /> : <Empty>从左侧选择主播后修改完整资料</Empty>}
      </Panel>
      <Panel title="粘贴手机分享" badge={<UserPlus size={17} />}>
        <Text size="sm" c="dimmed" mb="sm">把手机端“分享主页”复制出的整段文案直接粘贴到这里，系统会自动提取链接并识别主播。</Text>
        <Textarea label="主页分享文案或链接" value={profile} onChange={e => { setProfile(e.currentTarget.value); setPreview(undefined); }} autosize minRows={2} placeholder="例如：复制此链接，打开抖音搜索…… https://v.douyin.com/xxxx/" />
        <Group mt="sm"><Button loading={resolving} leftSection={<Link2 size={16}/>} onClick={resolveShare}>解析主播</Button><Button variant="subtle" disabled={!profile.trim()} onClick={() => { setName(''); setProfile(''); setLive(''); setPreview(undefined); }}>清空</Button></Group>
        {preview && <div className="sharePreview"><Group justify="space-between" align="flex-start"><Group gap="sm"><div className="avatar">{String(preview.nickname || '主').slice(0, 1)}</div><div><Group gap="xs"><Text fw={750}>{preview.nickname || '已识别主播'}</Text><Badge color={preview.is_live ? 'green' : 'orange'} variant="light">{preview.is_live ? '正在直播' : '当前未开播'}</Badge></Group><Text size="xs" c="dimmed">{preview.message}</Text>{preview.room_url && <Text size="xs" c="dimmed">直播间：{preview.room_url}</Text>}</div></Group><CheckCircle2 size={20} color="var(--accent)" /></Group><FieldGrid><TextInput label="主播名称" value={name} onChange={e => setName(e.currentTarget.value)} /><TextInput label="直播间地址" value={live} onChange={e => setLive(e.currentTarget.value)} /></FieldGrid><Button mt="md" onClick={addResolved}>确认加入主播库</Button></div>}
        {!preview && <Button mt="md" variant="light" disabled={!profile.trim() || resolving} onClick={() => add()}>暂不解析，直接保存</Button>}
      </Panel>
    </div>
  </PageGrid>;
}

function CollectionEditor({ anchors, recording, close, refresh, notify }: { anchors: Anchor[]; recording: boolean; close: () => void; refresh: () => Promise<void>; notify: (m: string, e?: boolean) => void }) {
  const [rows, setRows] = useState(() => anchors.map(item => ({...item, default_quality:item.default_quality||'原画', enabled_recording:item.enabled_recording!==false})));
  const [saving, setSaving] = useState(false); const [query, setQuery] = useState('');
  const update = (id: string, key: keyof Anchor, value: unknown) => setRows(current => current.map(row => row.id === id ? {...row,[key]:value} : row));
  const visible = rows.filter(row => !query || [row.name,row.profile_url,row.live_url].some(value => String(value||'').toLowerCase().includes(query.toLowerCase())));
  const save = async () => { setSaving(true); try { const data=await api<any>('/api/anchors/bulk',{anchors:rows.map(({id,name,profile_url,live_url,default_quality,enabled_recording,sec_user_id,web_rid,room_id,output_dir})=>({id,name,profile_url,live_url,default_quality,enabled_recording,sec_user_id,web_rid,room_id,output_dir}))}); setRows(data.anchors||rows); await refresh(); notify(`已保存 ${rows.length} 位主播的数据`); } catch(e) { notify((e as Error).message,true); } finally { setSaving(false); } };
  return <div className="wideColumn"><Panel title="主播数据集编辑" badge={<Badge variant="light">唯一数据源 · {rows.length} 位</Badge>} actions={<Group gap="xs"><Button variant="subtle" onClick={close}>返回主播库</Button><Button loading={saving} disabled={!rows.length || recording} onClick={save}>保存全部修改</Button></Group>}><Group justify="space-between" mb="md"><Text size="sm" c="dimmed">录制、直播监听、声音播放和作品拉取都读取这里的数据；保存后录制兼容配置会自动同步。</Text><TextInput w={280} value={query} onChange={e=>setQuery(e.currentTarget.value)} leftSection={<Search size={15}/>} placeholder="筛选主播或地址"/></Group>{recording&&<Text c="orange" size="sm" mb="sm">录制服务正在运行，请停止录制后再批量修改数据集。</Text>}<div className="dataTableWrap"><Table striped highlightOnHover withTableBorder withColumnBorders verticalSpacing="sm"><Table.Thead><Table.Tr><Table.Th>录制</Table.Th><Table.Th>主播名称</Table.Th><Table.Th>主页 / 分享地址</Table.Th><Table.Th>直播间地址</Table.Th><Table.Th>画质</Table.Th><Table.Th>状态</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{visible.map(row=><Table.Tr key={row.id}><Table.Td><Switch checked={row.enabled_recording!==false} onChange={e=>update(row.id,'enabled_recording',e.currentTarget.checked)}/></Table.Td><Table.Td><TextInput value={row.name} onChange={e=>update(row.id,'name',e.currentTarget.value)} w={160}/></Table.Td><Table.Td><TextInput value={row.profile_url} onChange={e=>update(row.id,'profile_url',e.currentTarget.value)} w={330}/></Table.Td><Table.Td><TextInput value={row.live_url||''} onChange={e=>update(row.id,'live_url',e.currentTarget.value)} w={280}/></Table.Td><Table.Td><Select value={row.default_quality||'原画'} onChange={v=>update(row.id,'default_quality',v||'原画')} data={['原画','超清','高清','标清','流畅']} w={100}/></Table.Td><Table.Td><StatusBadge value={row.last_live_status}/></Table.Td></Table.Tr>)}</Table.Tbody></Table></div>{!visible.length&&<Empty>数据集中没有符合条件的主播</Empty>}</Panel></div>;
}

function AnchorEditor({ anchor, run, notify, navigate, setActiveAnchorId }: { anchor: Anchor; run: (fn: () => Promise<any>, m: string) => void; notify: (m: string, e?: boolean) => void; navigate: (p: string) => void; setActiveAnchorId: (value: string) => void }) {
  const [form, setForm] = useState({ name: anchor.name, profile_url: anchor.profile_url, live_url: anchor.live_url, default_quality: anchor.default_quality || '原画', sec_user_id: anchor.sec_user_id || '', web_rid: anchor.web_rid || '', room_id: anchor.room_id || '', output_dir: anchor.output_dir || '', enabled_recording: anchor.enabled_recording !== false });
  const field = (key: keyof typeof form, value: string | boolean | null) => setForm(current => ({...current,[key]:value ?? ''}));
  const save = () => run(() => api(`/api/anchors/${anchor.id}`, form), '主播数据已保存');
  return <><Group justify="space-between" mb="md"><Group gap="xs"><Database size={18}/><div><Text fw={750}>基础资料</Text><Text size="xs" c="dimmed">录制、监听与作品拉取共享这一条数据</Text></div></Group><Switch checked={form.enabled_recording} onChange={e=>field('enabled_recording',e.currentTarget.checked)} label="参与自动录制" /></Group><FieldGrid><TextInput label="主播名称" value={form.name} onChange={e => field('name',e.currentTarget.value)} /><Select label="默认画质" value={form.default_quality} onChange={v => field('default_quality',v)} data={['原画','超清','高清','标清','流畅']} /><Textarea className="wide" label="主页 / 分享链接" value={form.profile_url} onChange={e => field('profile_url',e.currentTarget.value)} autosize /><TextInput className="wide" label="直播间地址" value={form.live_url} onChange={e => field('live_url',e.currentTarget.value)} /></FieldGrid><Accordion variant="contained" mt="md"><Accordion.Item value="advanced"><Accordion.Control>高级标识与存储</Accordion.Control><Accordion.Panel><FieldGrid><TextInput label="sec_user_id" description="主播账号的稳定标识" value={form.sec_user_id} onChange={e=>field('sec_user_id',e.currentTarget.value)}/><TextInput label="web_rid" description="直播间网页标识" value={form.web_rid} onChange={e=>field('web_rid',e.currentTarget.value)}/><TextInput label="room_id" description="当前解析到的房间 ID" value={form.room_id} onChange={e=>field('room_id',e.currentTarget.value)}/><Group className="wide" align="end" wrap="nowrap"><TextInput flex={1} label="主播独立保存目录" description="留空时使用全局录像目录" value={form.output_dir} onChange={e=>field('output_dir',e.currentTarget.value)}/><Button variant="light" leftSection={<FolderOpen size={15}/>} onClick={async()=>{const value=await window.liveRecorderDesktop?.chooseOutputDirectory();if(value)field('output_dir',value)}}>选择</Button></Group></FieldGrid></Accordion.Panel></Accordion.Item></Accordion><Group mt="md"><Button onClick={save}>保存主播数据</Button><Button variant="light" onClick={() => run(() => api(`/api/anchors/${anchor.id}/resolve`, {}), '直播间已重新解析')}>自动补全标识</Button><Button variant="subtle" disabled={!form.live_url} leftSection={<Radio size={15} />} onClick={() => { setActiveAnchorId(anchor.id); navigate('interact'); }}>用于监听</Button><Button variant="subtle" color="red" onClick={() => confirm('确定删除这个主播吗？') && run(() => api(`/api/anchors/${anchor.id}`, undefined, 'DELETE'), '主播已删除')}>删除</Button></Group><Text size="xs" c="dimmed" mt="md">系统维护：状态 {anchor.last_live_status || 'unknown'} · 最近巡检 {anchor.last_resolved_at ? new Date(anchor.last_resolved_at * 1000).toLocaleString() : '尚未巡检'}</Text>{anchor.last_check_error && <Text c="red" size="sm" mt="sm">{anchor.last_check_error}</Text>}</>;
}
