import { Badge, Button, Card, Group, Stack, Text, Title, type ButtonProps } from '@mantine/core';
import type { ReactNode } from 'react';

export function Panel({ title, badge, actions, children }: { title: string; badge?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return <Card className="panel" radius="lg" padding={0} withBorder>
    <Group className="panelHeader" justify="space-between" wrap="nowrap">
      <Group gap="sm"><Title order={3}>{title}</Title>{badge}</Group>{actions}
    </Group>
    <div className="panelBody">{children}</div>
  </Card>;
}

export function Empty({ children }: { children: ReactNode }) { return <div className="empty"><Text c="dimmed">{children}</Text></div>; }
export function StatusBadge({ value }: { value?: string }) {
  const map: Record<string, [string, string]> = { live: ['已开播', 'green'], incomplete: ['资料不完整', 'orange'], missed: ['疑似漏录', 'red'], offline: ['未开播', 'gray'], error: ['地址异常', 'red'], unknown: ['状态未知', 'gray'], recording: ['直播录制中', 'red'], reconnecting: ['断流重连中', 'orange'], finalizing: ['正在整理录像', 'blue'], waiting: ['等待开播', 'yellow'], pending: ['等待中', 'yellow'], stopped: ['服务已停止', 'gray'], uploading: ['上传中', 'blue'], completed: ['已完成', 'green'], failed: ['失败', 'red'], paused: ['已暂停', 'gray'], cancelled: ['已取消', 'gray'] };
  const [label, color] = map[value || 'unknown'] || [value || '未知', 'gray'];
  return <Badge variant="light" color={color}>{label}</Badge>;
}
export function ActionButton({ children, ...props }: ButtonProps & { children: ReactNode }) { return <Button radius="md" {...props}>{children}</Button>; }
export function FieldGrid({ children }: { children: ReactNode }) { return <div className="fieldGrid">{children}</div>; }
export function PageGrid({ children, wide = false }: { children: ReactNode; wide?: boolean }) { return <div className={wide ? 'pageGrid wide' : 'pageGrid'}>{children}</div>; }
export function Section({ children }: { children: ReactNode }) { return <Stack gap="sm" className="section">{children}</Stack>; }

export const formatBytes = (size = 0) => size < 1024 ? `${size} B` : size < 1048576 ? `${(size / 1024).toFixed(1)} KB` : size < 1073741824 ? `${(size / 1048576).toFixed(1)} MB` : `${(size / 1073741824).toFixed(1)} GB`;
export const roomUrl = (value = '') => String(value).match(/https?:\/\/[^\s,，]+/)?.[0] || String(value);
export const roomLabel = (value = '') => String(value).match(/主播\s*[:：]\s*([^,，]+)/)?.[1]?.trim() || (() => { try { return new URL(roomUrl(value)).hostname; } catch { return '直播间'; } })();
export const anchorLiveUrl = (anchor?: { profile_url?: string; live_url?: string }) => {
  const live = roomUrl(anchor?.live_url || '');
  if (live) return live;
  const profile = roomUrl(anchor?.profile_url || '');
  return profile.includes('live.douyin.com/') ? profile : '';
};
