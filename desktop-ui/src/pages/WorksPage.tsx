import { Accordion, Badge, Button, Checkbox, Group, SimpleGrid, Text, TextInput } from '@mantine/core';
import { FolderOpen, Play } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../api';
import { PageGrid, Panel } from '../components';
import type { AppState } from '../types';
import { AnchorPicker } from '../AnchorPicker';

export function WorksPage({ state, notify, activeAnchorId, setActiveAnchorId, logs, clearLogs }: { state: AppState; notify: (m: string, e?: boolean) => void; activeAnchorId: string; setActiveAnchorId: (value: string) => void; logs: string[]; clearLogs: () => void }) {
  const activeAnchor = state.anchors.find(item=>item.id===activeAnchorId);
  const [url, setUrl] = useState(activeAnchor?.profile_url || activeAnchor?.sec_user_id || ''); const [customUrl, setCustomUrl] = useState(false); const [output, setOutput] = useState(state.settings.output_path || ''); const [force, setForce] = useState(false);
  useEffect(() => { const anchor=state.anchors.find(item=>item.id===activeAnchorId); setUrl(anchor?.profile_url || anchor?.sec_user_id || ''); setCustomUrl(false); }, [activeAnchorId]);
  const [starting, setStarting] = useState(false);
  const [started, setStarted] = useState(false);
  const running = Boolean(state.work_pull?.running);
  useEffect(() => { if (running) setStarted(false); }, [running]);
  const start = async () => {
    if (starting || running || started || !url.trim()) return;
    setStarting(true);
    try { await api('/api/work-pull/start', { anchor_id: customUrl ? undefined : activeAnchorId || undefined, user_url: url.trim(), output_path: output, force }); setStarted(true); notify('作品拉取任务已开始'); }
    catch (e) { notify((e as Error).message, true); }
    finally { setStarting(false); }
  };
  useEffect(() => { if (!started) return; const timer = setTimeout(() => setStarted(false), 5000); return () => clearTimeout(timer); }, [started]);
  const stats = state.work_pull?.stats || {};
  return <PageGrid>
    <div className="column"><Panel title="作品拉取" badge={<Badge variant="light" color={running?'blue':'gray'}>{running?'拉取中':'待开始'}</Badge>}>
      <AnchorPicker state={state} value={activeAnchorId} onChange={setActiveAnchorId} includeProfiles disabled={running || starting}/>
      <Text size="sm" c="dimmed" mt="md">下载所选主播的公开作品，已下载的作品会自动跳过。</Text>
      <TextInput mt="md" label="作品入口" description="默认读取所选主播资料；手动修改时仅覆盖本次任务" value={url} onChange={e => { setUrl(e.currentTarget.value); setCustomUrl(true); }} placeholder="用户主页 / 分享链接 / sec_user_id" />
      <Group mt="md" align="end" wrap="nowrap"><TextInput flex={1} label="保存目录" placeholder="留空使用录像保存目录" value={output} onChange={e => setOutput(e.currentTarget.value)} /><Button variant="default" disabled={!window.liveRecorderDesktop} onClick={async () => { try { const value = await window.liveRecorderDesktop?.chooseOutputDirectory(); if (value) setOutput(value); } catch(e) { notify((e as Error).message,true); } }}>选择目录</Button></Group>
      <Accordion variant="contained" mt="md"><Accordion.Item value="advanced"><Accordion.Control>历史扫描选项</Accordion.Control><Accordion.Panel><Checkbox checked={force} onChange={e => setForce(e.currentTarget.checked)} label="重新扫描历史页面" description="仍会跳过已记录的作品，不重复下载。" /></Accordion.Panel></Accordion.Item></Accordion>
      <Group mt="lg"><Button leftSection={<Play size={16} />} loading={starting} disabled={running || started || !url.trim()} onClick={start}>{running?'正在拉取作品':started?'任务已提交':'开始拉取作品'}</Button><Button variant="subtle" leftSection={<FolderOpen size={16} />} onClick={() => api('/api/open-work-output', { output_path: output }).catch(e => notify(e.message, true))}>打开目录</Button></Group>
      {state.work_pull?.message && <Text size="xs" c="dimmed" mt="sm" role="status">{state.work_pull.message}</Text>}
    </Panel></div>
    <div className="column"><Panel title="任务统计"><SimpleGrid cols={{base:2,sm:3,lg:5}}>{[['已检查',stats.fetched],['新增',stats.new],['已下载',stats.downloaded],['跳过',stats.skipped],['失败',stats.failed]].map(([label,value])=><div className="stat" key={String(label)}><Text size="xl" fw={750} c={label==='失败'&&Number(value)>0?'red':undefined}>{value || 0}</Text><Text size="xs" c="dimmed">{label}</Text></div>)}</SimpleGrid></Panel><Panel title="拉取日志" actions={<Button size="xs" variant="subtle" disabled={!logs.length} onClick={clearLogs}>清空显示</Button>}><pre className="logBox tall">{logs.length ? logs.join('\n') : '选择主播并开始拉取后，这里会显示进度。'}</pre></Panel></div>
  </PageGrid>;
}
