import { useCallback, useEffect, useRef, useState } from 'react';
import { ExternalLink, LoaderCircle, Square, Video, X } from 'lucide-react';
import { api } from './api';
import type { AppState } from './types';
import { anchorStatus, sortedAnchors } from './anchorStatus';

const emptyState: AppState = { anchors: [], settings: {}, status: {}, baidupan: {}, update: {}, interaction: {}, work_pull: {}, recordings: [], recording_groups: [] };

export function MiniControls() {
  const [state, setState] = useState<AppState>(emptyState);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(() => localStorage.getItem('liveRecorderSelectedAnchor') || '');
  const [message, setMessage] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const searchInput = useRef<HTMLInputElement>(null);
  const refreshing = useRef(false);
  const refresh = useCallback(async () => {
    if (refreshing.current) return;
    refreshing.current = true;
    try { setState(await api<AppState>('/api/state')); setReady(true); setConnectionError(''); }
    catch (reason) { setConnectionError((reason as Error).message); }
    finally { refreshing.current = false; }
  }, []);
  useEffect(() => { void refresh(); const timer = window.setInterval(refresh, 2500); return () => window.clearInterval(timer); }, [refresh]);
  useEffect(() => { if (expanded) searchInput.current?.focus(); }, [expanded]);
  useEffect(() => {
    const sync = (event: StorageEvent) => { if (event.key === 'liveRecorderSelectedAnchor') setSelected(event.newValue || ''); };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, []);
  const running = Boolean(state.status?.running);
  const recording = Object.values(state.status?.room_states || {}).filter((item: any) => item?.state === 'recording').length;
  const toggle = async () => {
    setBusy(true); setError(''); setMessage('');
    try {
      await api(running ? '/api/stop' : '/api/start', running ? {} : { settings: state.settings });
      await refresh();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };
  const status = connectionError ? '连接中断 · 正在重连' : error ? '操作失败' : recording ? `${recording} 路录制中` : running ? '正在巡检' : '录制已停止';
  const liveCount = state.anchors.filter(a => anchorStatus(a, state).live).length;
  const expand = async () => {
    try { await window.liveRecorderDesktop?.setMiniExpanded(!expanded); setExpanded(!expanded); }
    catch (reason) { setError((reason as Error).message); }
  };
  const run = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true); setError(''); setMessage('');
    try { await action(); setMessage(success); await refresh(); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };
  const anchors = sortedAnchors(state, query);
  const selectedAnchor = state.anchors.find(anchor=>anchor.id===selected);
  const selectedInfo = selectedAnchor ? anchorStatus(selectedAnchor,state) : undefined;
  return <div className={`miniShell ${expanded ? 'expanded' : ''}`} onKeyDown={event => { if (event.key === 'Escape' && expanded) void expand(); }}><div className={`miniBar ${recording ? 'recording' : running ? 'running' : ''}`} title={connectionError || error || status}>
    <div className="miniDrag"><span className="miniDot"/><div className="miniStatus"><strong>{status}</strong><span>{ready ? (running ? '自动录制服务运行中' : '展开选择主播与录制') : '正在连接…'}</span></div></div>
    <button className="miniPrimary" onClick={expand} aria-expanded={expanded} title="选择主播，查看开播状态">开播 {liveCount} {expanded ? '▴' : '▾'}</button>
    <button className="miniIcon" onClick={() => window.liveRecorderDesktop?.openMainWindow()} title="打开主界面"><ExternalLink size={15}/></button>
    <button className="miniIcon close" onClick={() => window.liveRecorderDesktop?.closeMiniControls()} title="关闭悬浮条"><X size={16}/></button>
  </div>{expanded && <div className="miniPanel">
    <input ref={searchInput} aria-label="搜索主播" placeholder="搜索主播或历史昵称" value={query} onChange={event => setQuery(event.target.value)}/>
    <div className="miniToolbar"><span>{state.anchors.length} 位主播 · 点击名字选择</span><button disabled={busy} onClick={() => run(() => api('/api/anchors/check-live', {}), '开播状态已更新')}>{busy ? '处理中…' : '刷新状态'}</button></div>
    <div className="miniAnchorList">{anchors.map(anchor => {
      const info = anchorStatus(anchor, state);
      return <div className={`miniAnchor ${selected === anchor.id ? 'selected' : ''}`} key={anchor.id}>
        <button className="miniAnchorSelect" onClick={() => { setSelected(anchor.id); localStorage.setItem('liveRecorderSelectedAnchor', anchor.id); }} aria-pressed={selected === anchor.id}>
          <strong>{selected === anchor.id && <span className="miniCheck">✓ </span>}{anchor.name}</strong><span className={info.live ? 'isLive' : ''}>{info.label}</span>
        </button>
        <small title={anchor.last_check_error || ''}>{info.checkedLabel} · {anchor.enabled_recording === false ? '未加入自动录制' : '已加入自动录制'}</small>

      </div>;
    })}{!anchors.length && <div className="miniEmpty">{query ? '没有匹配的主播，试试其他名字' : '还没有主播，请在主界面添加'}{query && <button onClick={() => setQuery('')}>清空搜索</button>}</div>}</div>
    <section className="miniSelectedActions" aria-label="所选主播操作"><div className="miniSelectedName" title={selectedAnchor?.name}>当前选择：{selectedAnchor?.name||'请先选择主播'}</div>        {selectedAnchor && selectedInfo && <div className="miniAnchorActions">
          <button disabled={busy || !selectedInfo.url} onClick={() => run(async () => { await window.liveRecorderDesktop?.openExternal(selectedInfo.url); }, '已打开直播间')}>打开直播间</button>
          <button disabled={busy || selectedInfo.recording} onClick={() => run(async () => {
            await api(`/api/anchors/${selectedAnchor.id}/use-recording`, {});
            if (!running) await api('/api/start', { settings: state.settings });
          }, '已加入自动录制；开播后自动录制')}>{selectedInfo.recording ? '正在录制' : '加入自动录制'}</button>
          <button disabled={busy} onClick={() => run(() => api(`/api/anchors/${selectedAnchor.id}/resolve`, {}), '该主播状态已更新')}>检查状态</button>
        </div>}</section>
    {(connectionError || error || message) && <div className={`miniMessage ${connectionError || error ? 'failed' : ''}`} role="status">{connectionError || error || message}</div>}
    <button className={`miniGlobal ${running ? 'stop' : ''}`} disabled={!ready || busy || !!connectionError} onClick={toggle}>
      {busy ? <LoaderCircle className="miniSpin" size={14}/> : running ? <Square size={14}/> : <Video size={14}/>}{running ? '停止全部录制并保存' : '启动自动录制服务'}
    </button>
    <small>全局操作会影响所有已加入自动录制的主播。</small>
  </div>}</div>;
}
