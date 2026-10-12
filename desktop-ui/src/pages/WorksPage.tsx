import { Button, Checkbox, Group, SimpleGrid, Text, TextInput } from '@mantine/core';
import { FolderOpen, Play } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../api';
import { PageGrid, Panel } from '../components';
import type { AppState } from '../types';

export function WorksPage({ state, notify }: { state: AppState; notify: (m: string, e?: boolean) => void }) {
  const [url, setUrl] = useState(''); const [output, setOutput] = useState(state.settings.output_path || ''); const [force, setForce] = useState(false); const [logs, setLogs] = useState<string[]>([]); const [cursor, setCursor] = useState(0);
  useEffect(() => { const poll = async () => { try { const data = await api<any>(`/api/work-pull/logs?cursor=${cursor}`); if (data.lines?.length) setLogs(v => [...v, ...data.lines].slice(-1000)); setCursor(data.cursor || 0); } catch {} }; poll(); const timer = setInterval(poll, 1000); return () => clearInterval(timer); }, [cursor]);
  const start = async () => { try { await api('/api/work-pull/start', { user_url: url, output_path: output, force }); notify('作品拉取任务已开始'); } catch (e) { notify((e as Error).message, true); } };
  const stats = state.work_pull?.stats || {};
  return <PageGrid>
    <div className="column"><Panel title="作品拉取" badge={<Text size="sm" c={state.work_pull?.running ? 'blue' : 'dimmed'}>{state.work_pull?.message || '未开始'}</Text>}>
      <TextInput label="用户主页 / 分享链接 / sec_user_id" value={url} onChange={e => setUrl(e.currentTarget.value)} placeholder="粘贴抖音用户入口" />
      <Group mt="md" align="end" wrap="nowrap"><TextInput flex={1} label="保存目录（留空使用录像目录）" value={output} onChange={e => setOutput(e.currentTarget.value)} /><Button variant="light" onClick={async () => { const value = await window.liveRecorderDesktop?.chooseOutputDirectory(); if (value) setOutput(value); }}>选择</Button></Group>
      <Checkbox mt="md" checked={force} onChange={e => setForce(e.currentTarget.checked)} label="强制扫描历史页（仍跳过已记录作品 ID）" />
      <Group mt="lg"><Button leftSection={<Play size={16} />} loading={!!state.work_pull?.running} onClick={start}>开始拉取作品</Button><Button variant="light" leftSection={<FolderOpen size={16} />} onClick={() => api('/api/open-work-output', { output_path: output }).catch(e => notify(e.message, true))}>打开保存目录</Button></Group>
    </Panel></div>
    <div className="column"><Panel title="任务统计"><SimpleGrid cols={5}>{[['已检查',stats.fetched],['新增',stats.new],['已下载',stats.downloaded],['跳过',stats.skipped],['失败',stats.failed]].map(([label,value])=><div className="stat" key={String(label)}><Text size="xl" fw={800}>{value || 0}</Text><Text size="xs" c="dimmed">{label}</Text></div>)}</SimpleGrid></Panel><Panel title="拉取日志" actions={<Button size="xs" variant="subtle" onClick={() => setLogs([])}>清空</Button>}><pre className="logBox tall">{logs.length ? logs.join('\n') : '等待开始拉取…'}</pre></Panel></div>
  </PageGrid>;
}
