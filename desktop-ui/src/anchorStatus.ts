import { anchorLiveUrl } from './components';
import type { Anchor, AppState } from './types';

export function anchorStatus(anchor: Anchor, state: AppState) {
  const recording = Boolean(state.status.running && state.status.room_states?.[anchor.id]?.state === 'recording');
  const checked = anchor.last_resolved_at || 0;
  const fresh = checked > 0 && Date.now() / 1000 - checked < 180;
  const live = recording || (fresh && anchor.last_live_status === 'live');
  const label = recording ? '录制中' : !fresh ? '待确认' : anchor.last_live_status === 'error' ? '检测失败' : live ? '正在直播' : anchor.last_live_status === 'offline' ? '未开播' : '待确认';
  const age = Math.max(0, Math.floor(Date.now() / 1000 - checked));
  const checkedLabel = !checked ? '尚未检查' : age < 60 ? '刚刚检查' : age < 3600 ? `${Math.floor(age / 60)} 分钟前检查` : age < 86400 ? `${Math.floor(age / 3600)} 小时前检查` : `${Math.floor(age / 86400)} 天前检查`;
  return { recording, live, label, fresh, rank: recording ? 0 : live ? 1 : 2,
    checkedLabel,
    url: anchorLiveUrl(anchor) };
}

export function sortedAnchors(state: AppState, query = '') {
  return state.anchors.filter(a => [a.name, ...(a.aliases?.names || [])].some(name => name.toLowerCase().includes(query.trim().toLowerCase())))
    .sort((a, b) => anchorStatus(a, state).rank - anchorStatus(b, state).rank || a.name.localeCompare(b.name, 'zh-CN'));
}
