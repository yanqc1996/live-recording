import { ActionIcon, Badge, Button, Group, Menu, Text, Tooltip } from '@mantine/core';
import { Activity, BriefcaseBusiness, Bug, Headphones, Menu as MenuIcon, MoreHorizontal, PanelLeftClose, Radio, Square, Video } from 'lucide-react';
import { useState } from 'react';

type Props = {
  title: string; subtitle: string; sidebar: boolean; toggleSidebar: () => void;
  running: boolean; listening: boolean; audioPlaying: boolean; selectedName?: string;
  workMode: boolean; compact: boolean; taskCount: number; debugEnabled: boolean;
  onRecord: () => Promise<void>; onListen: () => Promise<void>; onAudio: () => Promise<void>;
  onTasks: () => void; onWorkMode: () => void; onCompact: () => void; onDebug: () => void;
  connectionError?: string; retry: () => void;
  playingName?: string; listeningName?: string;
};

export function WorkspaceHeader(props: Props) {
  const [pending, setPending] = useState('');
  const perform = async (key: string, action: () => Promise<void>) => {
    if (pending) return;
    setPending(key);
    try { await action(); } finally { setPending(''); }
  };
  return <header className="topbar workspaceHeader">
    <Group className="workspaceHeading" gap="sm" wrap="nowrap">
      <Tooltip label={props.sidebar ? '收起导航' : '展开导航'}><ActionIcon aria-label={props.sidebar ? '收起导航' : '展开导航'} variant="subtle" onClick={props.toggleSidebar}>{props.sidebar ? <PanelLeftClose size={19}/> : <MenuIcon size={19}/>}</ActionIcon></Tooltip>
      <div className="workspaceTitle"><Text fw={750} size="lg">{props.workMode ? `${props.title}.tsx` : props.title}</Text><Text size="xs" c="dimmed">{props.subtitle}</Text><div className="workspaceContext"><span title={props.selectedName}>当前选择：<strong>{props.selectedName || '未选择主播'}</strong></span>{props.audioPlaying&&<span title={props.playingName}>声音：{props.playingName||'正在播放'}</span>}{props.listening&&<span title={props.listeningName}>监听：{props.listeningName||'已连接'}</span>}</div></div>
    </Group>
    <Group className="workspaceActions" gap="xs">
      <Badge variant="dot" color={props.running ? 'green' : 'gray'} className="headerService">{props.running ? '录制服务运行中' : '录制服务未启动'}</Badge>
      <Tooltip label={props.running ? '停止所有主播的录制，并保存文件' : '监控所有已加入自动录制的主播'}><Button size="xs" variant={props.running ? 'light' : 'filled'} color={props.running ? 'red' : 'blue'} leftSection={props.running ? <Square size={14}/> : <Video size={14}/>} loading={pending === 'record'} disabled={!!pending && pending !== 'record'} onClick={() => void perform('record', props.onRecord)}>{props.running ? '停止全部' : '启动录制'}</Button></Tooltip>
      <Tooltip label={props.selectedName ? `当前主播：${props.selectedName}` : '请先在主播库选择主播'}><Button size="xs" variant="light" leftSection={props.listening ? <Square size={14}/> : <Radio size={14}/>} loading={pending === 'listen'} disabled={!!pending && pending !== 'listen' || !props.selectedName && !props.listening} onClick={() => void perform('listen', props.onListen)}>{props.listening ? '停止监听' : '监听弹幕'}</Button></Tooltip>
      <Tooltip label={props.selectedName ? `当前主播：${props.selectedName}` : '请先选择主播'}><Button size="xs" variant="light" leftSection={<Headphones size={14}/>} loading={pending === 'audio'} disabled={!!pending && pending !== 'audio' || !props.selectedName && !props.audioPlaying} onClick={() => void perform('audio', props.onAudio)}>{props.audioPlaying ? '停止声音' : '听声音'}</Button></Tooltip>
      <Button size="xs" variant="default" leftSection={<Activity size={14}/>} onClick={props.onTasks}>任务{props.taskCount ? ` ${props.taskCount}` : ''}</Button>
      <Menu position="bottom-end" withinPortal shadow="md" width={200}>
        <Menu.Target><ActionIcon size={30} aria-label="窗口与显示选项" variant="default"><MoreHorizontal size={18}/></ActionIcon></Menu.Target>
        <Menu.Dropdown><Menu.Label>窗口与显示</Menu.Label><Menu.Item leftSection={<BriefcaseBusiness size={15}/>} onClick={props.onWorkMode}>{props.workMode ? '退出工作模式' : '工作模式'}</Menu.Item><Menu.Item onClick={props.onCompact}>{props.compact ? '退出小窗模式' : '小窗模式'}</Menu.Item>{props.debugEnabled && <Menu.Item leftSection={<Bug size={15}/>} onClick={props.onDebug}>接口 Debug</Menu.Item>}</Menu.Dropdown>
      </Menu>
    </Group>
    {props.connectionError && <div className="connectionBanner" role="status"><span>本地服务连接中断，显示的是上次数据。正在自动重连。</span><Button size="compact-xs" variant="subtle" onClick={props.retry}>立即重连</Button></div>}
  </header>;
}
