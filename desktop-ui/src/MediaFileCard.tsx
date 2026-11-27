import { Badge, Button, Group, Text } from '@mantine/core';
import { Play } from 'lucide-react';
import { formatBytes } from './components';
import { archivePresentation } from './archivePresentation';

export function MediaFileCard({ file, checking, onCheck, onPlay }: { file: any; checking: boolean; onCheck: () => void; onPlay: () => void }) {
  const kind = ({ video: '视频', audio: '音频', image: '图片' } as Record<string,string>)[file.kind] || '文件';
  const detail = file.archive_detail || {};
  const { cloud, color, local } = archivePresentation(file);
  return <div className="mediaFileCard">
    <Text fw={600} size="sm" truncate title={file.name}>{file.name}</Text>
    <Text size="xs" c="dimmed" mt={5}>{new Date(file.modified*1000).toLocaleString()} · {kind} · {formatBytes(file.size)}{file.integrity?.duration_seconds?` · ${Math.round(file.integrity.duration_seconds/60)} 分钟`:''}</Text>
    <Group gap={6} mt="sm">
      {file.integrity&&<Badge size="xs" variant="light" color={file.integrity.status==='healthy'?'green':file.integrity.status==='warning'?'yellow':'red'}>{file.integrity.status==='healthy'?'校验通过':file.integrity.status==='warning'?'需要检查':'校验失败'}</Badge>}
      {file.source==='works'&&<Badge size="xs" variant="light" color="gray">公开作品</Badge>}
    </Group>
    <dl className="mediaArchiveState"><div><dt>本地</dt><dd>{local}</dd></div>{file.source==='recording'&&<div><dt>网盘</dt><dd className={`archiveState-${color}`}>{cloud}</dd></div>}</dl>
    {detail.cleanup_error&&<Text size="xs" c="orange" mt="xs">{detail.cleanup_error}</Text>}
    {(file.integrity?.error||file.integrity?.warning)&&<Text className="mediaFileIssue" size="xs" c={file.integrity?.error?'red':'orange'} mt="xs">{file.integrity.error||file.integrity.warning}</Text>}
    <Group justify="flex-end" gap="xs" mt="sm"><Button size="compact-xs" variant="subtle" loading={checking} onClick={onCheck}>校验文件</Button><Button size="compact-xs" variant="light" leftSection={<Play size={13}/>} disabled={!['video','audio'].includes(file.kind)} onClick={onPlay}>播放</Button></Group>
  </div>;
}
