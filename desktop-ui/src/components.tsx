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
  const map: Record<string, [string, string]> = { live: ['直播中', 'green'], offline: ['未开播', 'gray'], error: ['异常', 'red'], unknown: ['未巡检', 'gray'], recording: ['录制中', 'red'], pending: ['等待中', 'yellow'], uploading: ['上传中', 'blue'], completed: ['已完成', 'green'], failed: ['失败', 'red'], paused: ['已暂停', 'gray'], cancelled: ['已取消', 'gray'] };
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
