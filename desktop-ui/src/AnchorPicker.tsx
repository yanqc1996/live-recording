import { Badge, Group, Select, Text } from '@mantine/core';
import { anchorStatus, sortedAnchors } from './anchorStatus';
import type { AppState } from './types';

export function AnchorPicker({ state, value, onChange, includeProfiles = false, disabled = false }: { state: AppState; value: string; onChange: (id: string) => void; includeProfiles?: boolean; disabled?: boolean }) {
  const anchors = sortedAnchors(state).filter(a => includeProfiles || anchorStatus(a, state).url);
  const selected = anchors.find(a => a.id === value);
  const info = selected ? anchorStatus(selected, state) : undefined;
  return <div className="anchorPicker">
    <Select label="当前主播" placeholder="搜索并选择主播" searchable disabled={disabled} value={value || null} onChange={id => onChange(id || '')}
      nothingFoundMessage="没有匹配的主播" maxDropdownHeight={300}
      data={anchors.map(a => ({ value: a.id, label: a.name }))}
      renderOption={({ option }) => {
        const anchor = anchors.find(a => a.id === option.value)!;
        const status = anchorStatus(anchor, state);
        return <Group justify="space-between" w="100%" wrap="nowrap"><Text size="sm" truncate>{anchor.name}</Text><Badge size="xs" color={status.recording ? 'red' : status.live ? 'green' : 'gray'} variant="light">{status.label}</Badge></Group>;
      }}/>
    {info && <Group justify="space-between" mt="xs" gap="xs"><Badge color={info.recording ? 'red' : info.live ? 'green' : 'gray'} variant="light">{info.label}</Badge><Text size="xs" c="dimmed">{info.checkedLabel}</Text></Group>}
    <Text size="xs" c="dimmed" mt="xs">切换主播会同步当前监听与声音。</Text>
  </div>;
}
