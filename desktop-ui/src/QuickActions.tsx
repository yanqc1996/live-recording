import { Badge, Button, Group, Modal, Text, TextInput } from '@mantine/core';
import { useEffect, useState } from 'react';
import { api } from './api';
import { anchorLiveUrl } from './components';
import type { AppState } from './types';
import { anchorStatus, sortedAnchors } from './anchorStatus';

export function QuickActions({state,refresh,notify,startAudio,clearAudio}:{state:AppState;refresh:()=>Promise<void>;notify:(s:string,e?:boolean)=>void;startAudio:(id:string)=>Promise<void>;clearAudio:()=>void}) {
  const [open,setOpen]=useState(false);
  const [query,setQuery]=useState('');
  const [busy,setBusy]=useState(false);
  const [protectedAudio,setProtectedAudio]=useState(false);
  const [status,setStatus]=useState({shortcut:false,audioGuard:false});
  useEffect(()=>window.liveRecorderDesktop?.onQuickOpen(()=>setOpen(true)),[]);
  useEffect(()=>{
    const listener=(e:KeyboardEvent)=>{if((e.metaKey||e.ctrlKey)&&e.shiftKey&&e.code==='KeyK'){e.preventDefault();setOpen(true)}};
    window.addEventListener('keydown',listener);
    return()=>window.removeEventListener('keydown',listener);
  },[]);
  useEffect(()=>{
    if(open)window.liveRecorderDesktop?.getQuickStatus().then(setStatus).catch(()=>{});
  },[open]);
  useEffect(()=>window.liveRecorderDesktop?.onAudioRouteChanged(()=>{
    document.querySelectorAll<HTMLMediaElement>('audio,video').forEach(media=>media.pause());
    clearAudio();
    setProtectedAudio(true);
    void api('/api/interaction/audio-stop',{}).catch(()=>{});
    notify('声音输出发生变化，已静音并暂停播放；后台录制不受影响');
  }),[clearAudio,notify]);
  const run=async(action:()=>Promise<unknown>)=>{
    setBusy(true);try{await action();await refresh()}catch(e){notify((e as Error).message,true)}finally{setBusy(false)}
  };
  const resume=async()=>{await window.liveRecorderDesktop?.resumeAudio();setProtectedAudio(false)};
  const anchors=sortedAnchors(state, query);
  return <>
    <Group className="quickToolbar" mb="sm"><Button size="xs" variant="default" onClick={()=>setOpen(true)}>快捷操作 <kbd>{window.liveRecorderDesktop?.platform === 'darwin' ? '⌘ ⇧ K' : 'Ctrl ⇧ K'}</kbd></Button><Button size="xs" variant="subtle" onClick={()=>window.liveRecorderDesktop?.openMiniControls().catch(e=>notify(e.message,true))}>打开悬浮条</Button>{protectedAudio&&<Button size="xs" color="orange" onClick={()=>run(resume)}>声音保护已触发 · 允许再次播放</Button>}</Group>
    <Modal opened={open} onClose={()=>setOpen(false)} title="快捷操作" size="lg">
      <TextInput data-autofocus placeholder="搜索主播名称" value={query} onChange={e=>setQuery(e.currentTarget.value)} mb="md"/>
      {!anchors.length&&<Text c="dimmed">没有匹配的主播</Text>}
      <Button size="xs" variant="subtle" disabled={busy} mb="sm" onClick={()=>run(()=>api('/api/anchors/check-live',{}))}>刷新开播状态</Button>
      <div className="quickAnchorList">{anchors.map(anchor=><div className="quickAnchorCard" key={anchor.id}><Group justify="space-between" wrap="nowrap"><Text fw={650} truncate>{anchor.name}</Text><Badge color={anchorStatus(anchor,state).recording?'red':anchorStatus(anchor,state).live?'green':'gray'} variant="light">{anchorStatus(anchor,state).label}</Badge></Group><Text size="xs" c="dimmed" mt={4}>{anchorStatus(anchor,state).checkedLabel} · {anchor.enabled_recording===false?'未加入自动录制':'已加入自动录制'}</Text><Group gap="xs" mt="sm">
        <Button size="xs" disabled={busy} onClick={()=>run(async()=>{await resume();await startAudio(anchor.id)})}>听声音</Button>
        <Button size="xs" variant="light" disabled={busy||anchorStatus(anchor,state).recording} onClick={()=>run(async()=>{
          await api(`/api/anchors/${anchor.id}/use-recording`,{});
          if(!state.status.running)await api('/api/start',{settings:state.settings});
          notify('已加入自动录制；开播后开始录制，其他已启用主播仍参与录制');
        })}>{anchorStatus(anchor,state).recording?'正在录制':'加入自动录制'}</Button>
        <Button size="xs" variant="subtle" disabled={busy||!anchorLiveUrl(anchor)} onClick={()=>run(async()=>{
          const url=anchorLiveUrl(anchor);
          if(window.liveRecorderDesktop)await window.liveRecorderDesktop.openExternal(url);
          else window.open(url,'_blank','noopener,noreferrer');
        })}>打开直播间</Button>
      </Group></div>)}</div>
      <Text size="xs" c="dimmed" mt="md">{status.shortcut?'全局快捷键已启用':'可通过页面入口打开'} · {status.audioGuard?'声音输出切换保护已启用':'声音输出切换保护不可用'}</Text>
    </Modal>
  </>;
}
