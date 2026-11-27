import { Badge, Button, Group, Text } from '@mantine/core';
import { Play } from 'lucide-react';
import { formatBytes } from './components';

export function MediaFileCard({ file, checking, onCheck, onPlay }: { file: any; checking: boolean; onCheck: () => void; onPlay: () => void }) {
  const kind = ({ video: '视频', audio: '音频', image: '图片' } as Record<string,string>)[file.kind] || '文件';
  const detail = file.archive_detail || {};
  const when = (timestamp: number) => new Date(timestamp*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});
  const upload = ({success:['有上传成功记录','blue'],archived:['以完整文件归档','gray'],untracked:['未加入上传','yellow'],failed:['上传失败','red'],paused:['上传已暂停','gray'],cancelled:['上传已取消','gray'],uploading:['上传中','blue'],pending:['等待上传','blue']} as Record<string,string[]>)[file.upload_status] || ['未加入上传','gray'];
  if (detail.cleanup_error) { upload[0]='复核或清理需处理'; upload[1]='orange'; }
  else if (detail.remote_checked_at) { upload[0]=`${detail.merged_path?'完整文件':'文件'}已复核 · ${when(detail.remote_checked_at)}`; upload[1]='green'; }
  else if (file.upload_status==='success' && detail.upload_evidence!=='task') { upload[0]='曾上传，待复核'; upload[1]='orange'; }
  const local = detail.cleanup_error ? '已保留，等待处理' : detail.cleanup_due_at ? detail.cleanup_due_at>Date.now()/1000 ? `保留至 ${when(detail.cleanup_due_at)}` : '已到清理时间，等待处理' : detail.upload_evidence==='history' ? '已保留，等待归档复核' : '已保存在本机';
  return <div className="mediaFileCard">
    <Text fw={600} size="sm" truncate title={file.name}>{file.name}</Text>
    <Text size="xs" c="dimmed" mt={5}>{new Date(file.modified*1000).toLocaleString()} · {kind} · {formatBytes(file.size)}{file.integrity?.duration_seconds?` · ${Math.round(file.integrity.duration_seconds/60)} 分钟`:''}</Text>
    <Group gap={6} mt="sm">
      {file.integrity&&<Badge size="xs" variant="light" color={file.integrity.status==='healthy'?'green':file.integrity.status==='warning'?'yellow':'red'}>{file.integrity.status==='healthy'?'校验通过':file.integrity.status==='warning'?'需要检查':'校验失败'}</Badge>}
      {file.source==='works'&&<Badge size="xs" variant="light" color="gray">公开作品</Badge>}
    </Group>
    <dl className="mediaArchiveState"><div><dt>本地</dt><dd>{local}</dd></div>{file.source==='recording'&&<div><dt>网盘</dt><dd className={`archiveState-${upload[1]}`}>{upload[0]}</dd></div>}</dl>
    {detail.cleanup_error&&<Text size="xs" c="orange" mt="xs">{detail.cleanup_error}</Text>}
    {(file.integrity?.error||file.integrity?.warning)&&<Text className="mediaFileIssue" size="xs" c={file.integrity?.error?'red':'orange'} mt="xs">{file.integrity.error||file.integrity.warning}</Text>}
    <Group justify="flex-end" gap="xs" mt="sm"><Button size="compact-xs" variant="subtle" loading={checking} onClick={onCheck}>校验文件</Button><Button size="compact-xs" variant="light" leftSection={<Play size={13}/>} disabled={!['video','audio'].includes(file.kind)} onClick={onPlay}>播放</Button></Group>
  </div>;
}
