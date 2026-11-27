import { Button, Drawer, Group, Progress, Select, Text, TextInput } from '@mantine/core';
import { useEffect, useRef, useState } from 'react';
import { api, mediaAudioPreviewUrl } from './api';

type Job = {id:string; path:string; name:string; language:string; state:string; phase:string; progress:number; error:string; creator?:string; recorded_date?:string; source_exists?:boolean; matches?:{start:number;text:string}[]};
type Result = {text:string; srt:string; segments:{start:number;end:number;text:string}[]};

export function TranscriptionPanel({files,notify,archive=false}:{files:any[];notify:(message:string,error?:boolean)=>void;archive?:boolean}) {
  const [status,setStatus]=useState<any>({jobs:[]});
  const [path,setPath]=useState<string|null>(null);
  const [language,setLanguage]=useState<string|null>('zh');
  const [busy,setBusy]=useState(false);
  const [opened,setOpened]=useState<Job|null>(null);
  const [result,setResult]=useState<Result|null>(null);
  const [query,setQuery]=useState('');
  const [creator,setCreator]=useState('');
  const [date,setDate]=useState('');
  const [keyword,setKeyword]=useState('');
  const [records,setRecords]=useState<Job[]>([]);
  const [searchError,setSearchError]=useState('');
  const [play,setPlay]=useState<{url:string;start:number}|null>(null);
  const alive=useRef(true);
  const load=async()=>{const data=await api('/api/transcriptions');if(alive.current)setStatus(data)};
  useEffect(()=>{
    alive.current=true; let timer:number;
    const tick=async()=>{try{await load()}catch{}finally{if(alive.current)timer=window.setTimeout(tick,2000)}};
    tick(); return()=>{alive.current=false;clearTimeout(timer)};
  },[]);
  useEffect(()=>{if(path&&!files.some(file=>file.path===path))setPath(null)},[files,path]);
  useEffect(()=>{
    if(!archive)return;
    let cancelled=false;
    const timer=window.setTimeout(()=>{
      api<{jobs:Job[]}>(`/api/transcriptions/search?${new URLSearchParams({creator,date,query:keyword})}`)
        .then(data=>{if(!cancelled){setRecords(data.jobs);setSearchError('')}})
        .catch(e=>{if(!cancelled)setSearchError(e.message)});
    },300);
    return()=>{cancelled=true;clearTimeout(timer)};
  },[archive,creator,date,keyword,status]);
  const act=async(fn:()=>Promise<any>)=>{setBusy(true);try{await fn();await load()}catch(e){notify((e as Error).message,true)}finally{setBusy(false)}};
  const show=async(job:Job)=>{setResult(null);setPlay(null);setQuery('');const data=await api<{result:Result}>(`/api/transcriptions?id=${job.id}`);setOpened(job);setResult(data.result)};
  const download=(format:'txt'|'srt')=>{
    if(!result||!opened)return;
    const url=URL.createObjectURL(new Blob([format==='txt'?result.text:result.srt],{type:'text/plain;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download=`${opened.name}.${format}`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  return <section style={{marginBottom:20}}>
    <Text fw={700}>{archive?'转写记录':'本机录音转文字'}</Text>
    {archive&&<><Text size="sm" c="dimmed" mb="sm">上传前尝试转写，失败仍继续上传并按设置清理视频；失败后若原视频已删除，需从网盘下载才能补转写。文字独立保存在本机，删除原视频不影响查询。日期优先取录制文件名，否则取文件修改日期。</Text><Group grow mb="md"><TextInput label="主播" placeholder="输入主播名" value={creator} onChange={e=>setCreator(e.currentTarget.value)}/><TextInput label="录制日期" type="date" value={date} onChange={e=>setDate(e.currentTarget.value)}/><TextInput label="全文关键词" placeholder="查找直播说过的话" value={keyword} onChange={e=>setKeyword(e.currentTarget.value)}/></Group>{searchError&&<Text c="red">{searchError}</Text>}</>}
    <Text size="xs" c="dimmed" mb="sm">转写在本机完成，不向识别服务上传音视频；网盘上传仍按归档设置执行。单任务、2 个 CPU 线程，按 5 分钟分段处理；识别结果可能有误。</Text>
    {!status.engine_ready&&<Text size="xs" c="orange">本机缺少识别引擎，请安装 whisper.cpp（brew install whisper-cpp）。</Text>}
    {!status.model_ready&&<Group mb="sm"><Button size="xs" loading={status.download?.state==='downloading'} disabled={busy} onClick={()=>act(()=>api('/api/transcriptions/model',{}))}>下载识别模型（约 142 MiB）</Button><Text size="xs">{status.download?.state==='downloading'?`${status.download.progress}%`:status.download?.error}</Text></Group>}
    {!archive&&<><Select label="选择已录完的文件" searchable clearable value={path} onChange={setPath} data={files.filter(f=>['audio','video'].includes(f.kind)).map(f=>({value:f.path,label:f.name}))} placeholder="从当前媒体列表选择" />
    <Group mt="xs"><Select aria-label="转写语言" w={140} value={language} onChange={setLanguage} data={[{value:'zh',label:'中文'},{value:'en',label:'英文'},{value:'auto',label:'自动识别'}]}/><Button size="xs" disabled={!path||!status.engine_ready||!status.model_ready||busy} onClick={()=>act(()=>api('/api/transcriptions/start',{path,language}))}>开始转写</Button></Group>
    </>}
    {archive&&!records.length&&<Text c="dimmed">暂无匹配记录；已删除且未曾转写的视频无法补回文字。</Text>}
    {(archive?records:status.jobs).map((job:Job)=><div key={job.id} style={{marginTop:12}}><Text size="sm" truncate>{job.creator} · {job.recorded_date} · {job.name}</Text>{job.source_exists===false&&<Text size="xs" c="dimmed">原视频已移除，文字仍可查看和导出</Text>}<Text size="xs" c={job.state==='failed'?'red':'dimmed'}>{job.error||job.phase}</Text>{job.matches?.map((s,i)=><Text key={i} size="sm">{Math.floor(s.start/60)}:{String(Math.floor(s.start%60)).padStart(2,'0')} · {s.text}</Text>)}{['queued','running'].includes(job.state)&&<Progress value={job.progress} mt={4}/>}<Group gap="xs" mt={4}>
      {['queued','running'].includes(job.state)&&<Button size="compact-xs" variant="subtle" disabled={busy} onClick={()=>act(()=>api('/api/transcriptions/cancel',{id:job.id}))}>取消</Button>}
      {['failed','cancelled'].includes(job.state)&&<Button size="compact-xs" variant="light" disabled={busy} onClick={()=>act(()=>api('/api/transcriptions/start',{path:job.path,language:job.language}))}>重试</Button>}
      {job.state==='success'&&<Button size="compact-xs" variant="light" disabled={busy} onClick={()=>act(()=>show(job))}>查看文字</Button>}
    </Group></div>)}
    <Drawer opened={!!opened} onClose={()=>{setOpened(null);setPlay(null)}} title={opened?.name||'转写结果'} position="right" size="lg">
      <Group mb="sm"><Button size="xs" onClick={()=>download('txt')}>导出 TXT</Button><Button size="xs" onClick={()=>download('srt')}>导出 SRT</Button><Button size="xs" variant="subtle" onClick={()=>navigator.clipboard.writeText(result?.text||'').then(()=>notify('文字已复制')).catch(()=>notify('复制失败',true))}>复制文字</Button></Group>
      <TextInput placeholder="搜索转写内容" value={query} onChange={e=>setQuery(e.currentTarget.value)} mb="sm"/>
      {play&&<><Text size="xs" c="dimmed">从 {Math.floor(play.start/60)}:{String(Math.floor(play.start%60)).padStart(2,'0')} 开始播放</Text><audio key={play.url} src={play.url} controls autoPlay style={{width:'100%'}} onError={()=>notify('音频播放失败，请检查源文件是否仍然存在',true)}/></>}
      {result?.segments.filter(s=>s.text.toLowerCase().includes(query.toLowerCase())).map((s,i)=><div key={i} style={{marginTop:12}}><Button size="compact-xs" variant="subtle" disabled={opened?.source_exists===false} onClick={()=>opened&&setPlay({url:`${mediaAudioPreviewUrl(opened.path)}&start=${s.start}`,start:s.start})}>{Math.floor(s.start/60)}:{String(Math.floor(s.start%60)).padStart(2,'0')} ▶</Button><Text size="sm">{s.text}</Text></div>)}
      {result&&!result.segments.length&&<Text c="dimmed">未识别到可用语音。</Text>}
    </Drawer>
  </section>;
}
