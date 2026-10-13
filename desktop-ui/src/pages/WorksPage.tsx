import { Button, Checkbox, Group, Select, SimpleGrid, Text, TextInput } from '@mantine/core';
import { FolderOpen, Play } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../api';
import { PageGrid, Panel } from '../components';
import type { AppState } from '../types';

export function WorksPage({ state, notify, activeAnchorId, setActiveAnchorId, logs, clearLogs }: { state: AppState; notify: (m: string, e?: boolean) => void; activeAnchorId: string; setActiveAnchorId: (value: string) => void; logs: string[]; clearLogs: () => void }) {
  const activeAnchor = state.anchors.find(item=>item.id===activeAnchorId);
  const [url, setUrl] = useState(activeAnchor?.profile_url || activeAnchor?.sec_user_id || ''); const [customUrl, setCustomUrl] = useState(false); const [output, setOutput] = useState(state.settings.output_path || ''); const [force, setForce] = useState(false);
  useEffect(() => { const anchor=state.anchors.find(item=>item.id===activeAnchorId); setUrl(anchor?.profile_url || anchor?.sec_user_id || ''); setCustomUrl(false); }, [activeAnchorId]);
  const start = async () => { try { await api('/api/work-pull/start', { anchor_id: customUrl ? undefined : activeAnchorId || undefined, user_url: url, output_path: output, force }); notify('作品拉取任务已开始'); } catch (e) { notify((e as Error).message, true); } };
  const stats = state.work_pull?.stats || {};
  return <PageGrid>
    <div className="column"><Panel title="作品拉取" badge={<Text size="sm" c={state.work_pull?.running ? 'blue' : 'dimmed'}>{state.work_pull?.message || '未开始'}</Text>}>
      <Select label="选择主播" description="与直播监听、声音播放共用当前主播" value={activeAnchorId} onChange={value => setActiveAnchorId(value||'')} data={state.anchors.map(anchor=>({value:anchor.id,label:anchor.name}))} searchable clearable nothingFoundMessage="主播库中暂无主播" />
      <TextInput mt="md" label="作品入口" description="默认读取所选主播资料；手动修改时仅覆盖本次任务" value={url} onChange={e => { setUrl(e.currentTarget.value); setCustomUrl(true); }} placeholder="用户主页 / 分享链接 / sec_user_id" />
      <Group mt="md" align="end" wrap="nowrap"><TextInput flex={1} label="保存目录（留空使用录像目录）" value={output} onChange={e => setOutput(e.currentTarget.value)} /><Button variant="light" onClick={async () => { const value = await window.liveRecorderDesktop?.chooseOutputDirectory(); if (value) setOutput(value); }}>选择</Button></Group>
      <Checkbox mt="md" checked={force} onChange={e => setForce(e.currentTarget.checked)} label="强制扫描历史页（仍跳过已记录作品 ID）" />
      <Group mt="lg"><Button leftSection={<Play size={16} />} loading={!!state.work_pull?.running} onClick={start}>开始拉取作品</Button><Button variant="light" leftSection={<FolderOpen size={16} />} onClick={() => api('/api/open-work-output', { output_path: output }).catch(e => notify(e.message, true))}>打开保存目录</Button></Group>
    </Panel></div>
    <div className="column"><Panel title="任务统计"><SimpleGrid cols={5}>{[['已检查',stats.fetched],['新增',stats.new],['已下载',stats.downloaded],['跳过',stats.skipped],['失败',stats.failed]].map(([label,value])=><div className="stat" key={String(label)}><Text size="xl" fw={800}>{value || 0}</Text><Text size="xs" c="dimmed">{label}</Text></div>)}</SimpleGrid></Panel><Panel title="拉取日志" actions={<Button size="xs" variant="subtle" onClick={clearLogs}>清空</Button>}><pre className="logBox tall">{logs.length ? logs.join('\n') : '等待开始拉取…'}</pre></Panel></div>
  </PageGrid>;
}
