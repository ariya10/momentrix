import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Activity, ArrowDownRight, ArrowRight, ArrowUpRight, CheckCheck, ChevronRight, CirclePlay, Clapperboard, Clock3, Film, FolderClosed, Layers3, Plus, Radio, RefreshCw, Search, SlidersHorizontal, Workflow } from 'lucide-react'
import { Alert, Badge, Check, Empty, Field, Loading, PageHead, useApi } from '../components/common'
import { Button } from '../components/ui/button'
import { api, apiBase, date, label, time } from '../services/http'
import { terminal, type Clip, type Health, type Metrics, type Project, type Run } from '../types'

export function Stat({name,value,Icon}:{name:string;value:number|string;Icon:typeof Film}){
  return <div className="stat"><div className="stat-top"><span>{name}</span><Icon size={17} strokeWidth={1.6}/></div><strong>{value}</strong></div>
}
function TitleLink({title,to,text='View all'}:{title:string;to:string;text?:string}){return <div className="section-title"><h2>{title}</h2><Link to={to}>{text}<ArrowUpRight size={15}/></Link></div>}
function ProjectThumb({project}:{project:Project}) {
  const asset=project.assets[0]
  return <div className="project-thumb">{asset ? <img alt="" loading="lazy" src={apiBase+'/assets/'+asset.id+'/thumbnail'}/> : <FolderClosed size={22}/>}</div>
}
function ProjectRows({items}:{items:Project[]}) {
  if(!items.length)return <Empty title="No projects yet">Create a project to begin selecting clips from a source video.</Empty>
  return <div className="project-rows">{items.map(p=><Link to={'/projects/'+p.id} className="project-row" key={p.id}><ProjectThumb project={p}/><div className="row-name"><strong>{p.name}</strong><small>{label(p.content_type)} · {date(p.created_at)}</small></div><Badge value={p.runs[0]?.status||'created'}/><ChevronRight size={16}/></Link>)}</div>
}
export function Dashboard(){
  const metrics=useApi<Metrics>('/system/metrics',15000), projects=useApi<Project[]>('/projects',15000), health=useApi<Health>('/system/status',60000), clips=useApi<Clip[]>('/clips',15000), runs=useApi<Run[]>('/runs',12000)
  const m=metrics.data, pending=clips.data?.filter(c=>c.review.status==='pending') || []
  const pick=pending[0] || clips.data?.[0]
  return <><PageHead title="Studio dashboard" sub="Your projects, processing activity, and clips ready for review."/>
    <Alert error={metrics.error||projects.error||clips.error||runs.error}/>
    {m ? <section className="stat-grid"><Stat name="Total projects" value={m.total_projects} Icon={FolderClosed}/><Stat name="Processing now" value={m.processing_jobs} Icon={Activity}/><Stat name="Generated clips" value={m.total_clips} Icon={Clapperboard}/><Stat name="Approved clips" value={m.approved_clips} Icon={CheckCheck}/></section> : metrics.isPending && <Loading/>}
    <div className="dash-columns"><div className="dash-main"><section className="review-panel"><div className="section-title"><h2><span className="accent-line"/>Review queue</h2><Link to="/clips">Clip library<ArrowUpRight size={15}/></Link></div>
    {clips.isPending ? <Loading/> : pick ? <div className="featured-clip"><div className="featured-media"><video preload="metadata" muted playsInline controls src={apiBase+'/clips/'+pick.id+'/media#t=0.1'}/></div><div className="featured-copy"><Badge value={pick.review.status}/><h3>{pick.title}</h3><p>{pick.project_name}</p><div className="clip-facts"><span><Clock3 size={14}/>{time(pick.duration)}</span><span><Layers3 size={14}/>{pick.score}/100</span></div><Link className="btn secondary small" to={'/editor/'+pick.id}><SlidersHorizontal size={15}/>Open editor</Link></div></div> : <Empty title="Your review queue is empty">Generated clips will appear here for a preview and a decision.</Empty>}</section>
    <section className="panel"><TitleLink title="Recent projects" to="/projects"/>{projects.data?<ProjectRows items={projects.data.slice(0,5)}/>:projects.isPending&&<Loading/>}</section></div>
    <aside className="dash-side"><section className="panel"><TitleLink title="System health" to="/settings" text="Details"/><Alert error={health.error}/>{health.data?<><Check good={health.data.ffmpeg&&health.data.ffprobe} name="Media tools"/><Check good={health.data.whisper_model_available} name="Transcription"/><Check good={health.data.ollama_model_available} name="Local model"/><div className="disk"><span>Free disk space</span><strong>{(health.data.free_disk_bytes/1024**3).toFixed(1)} GiB</strong></div></>:health.isPending&&<Loading/>}</section>
    <section className="panel"><TitleLink title="Automation activity" to="/automation"/>{runs.data?.length?<div className="activity-list">{runs.data.slice(0,3).map(run=><Link key={run.id} to={'/projects/'+run.project_id}><span className="activity-icon"><Workflow size={16}/></span><div><strong>{label(run.stage||run.status)}</strong><small>{date(run.created_at)}</small></div></Link>)}</div>:runs.isPending?<Loading/>:<p className="muted">No runs recorded.</p>}</section>
    <div className="shortcuts"><Link to="/new"><Plus size={16}/>Upload a source<ArrowRight size={15}/></Link><Link to="/campaigns"><SlidersHorizontal size={16}/>Configure campaigns<ArrowRight size={15}/></Link></div></aside></div></>
}

export function Projects(){
  const query=useApi<Project[]>('/projects',12000),[filter,setFilter]=useState('')
  const items=query.data?.filter(p=>p.name.toLowerCase().includes(filter.toLowerCase()))
  return <><PageHead title="My projects" sub="Source media and processing history for your workspace."/><label className="search"><Search size={16}/><input placeholder="Search projects" aria-label="Search projects" value={filter} onChange={e=>setFilter(e.target.value)}/></label><Alert error={query.error}/>{query.isPending?<Loading/>:items&&<section className="panel"><ProjectRows items={items}/></section>}</>
}
function RunView({initial}:{initial:Run}){
  const query=useApi<Run>('/runs/'+initial.id, terminal.has(initial.status)?undefined:5000), client=useQueryClient()
  const run=query.data||initial
  const [clock,setClock]=useState(Date.now())
  const [actionErr,setActionErr]=useState('')
  const [busy,setBusy]=useState(false)
  useEffect(()=>{
    if(terminal.has(run.status))return
    const tick=window.setInterval(()=>setClock(Date.now()),1000)
    if(!window.EventSource)return ()=>clearInterval(tick)
    const source=new EventSource(apiBase+'/runs/'+initial.id+'/events')
    source.addEventListener('run',e=>{try{client.setQueryData(['/runs/'+initial.id],JSON.parse((e as MessageEvent).data))}catch{/* Polling refreshes invalid or interrupted event streams. */}})
    return ()=>{clearInterval(tick);source.close()}
  },[initial.id,run.status,client])
  async function action(type:string){
    setBusy(true);setActionErr('')
    try{await api('/runs/'+run.id+'/'+type,'POST');await client.invalidateQueries()}catch(e){setActionErr((e as Error).message)}finally{setBusy(false)}
  }
  const start=Date.parse(run.started_at||run.created_at), end=run.finished_at?Date.parse(run.finished_at):terminal.has(run.status)&&run.updated_at?Date.parse(run.updated_at):clock
  return <div className="run-summary"><div className="run-top"><div><strong>{label(run.stage||run.status)}</strong><small className="mono">Run {run.id.slice(0,10)}</small></div><Badge value={run.status}/></div>
    <dl className="facts"><dt>Started</dt><dd>{date(run.created_at)}</dd><dt>Elapsed</dt><dd>{time(Math.max(0,(end-start)/1000))}</dd>{run.processing_preset&&<><dt>Processing preset</dt><dd>{label(run.processing_preset)}</dd></>}{run.execution_id&&<><dt>n8n execution</dt><dd>{run.execution_id}</dd></>}{run.candidate_count!=null&&<><dt>Candidates</dt><dd>{run.candidate_count}</dd></>}{run.rendered_count!=null&&<><dt>Rendered clips</dt><dd>{run.rendered_count}</dd></>}</dl>
    {run.completed_stages?.length ? <details><summary>Completed stages</summary><p>{run.completed_stages.map(label).join(' · ')}</p></details> : null}
    <Alert error={query.error||run.error||actionErr}/>{run.warnings?.map((w,i)=><p className="warning" key={i}>{w}</p>)}<div className="actions">{!terminal.has(run.status)&&<Button variant="secondary" disabled={busy} onClick={()=>action('cancel')}>Cancel run</Button>}{['failed','cancelled','dispatch_failed','awaiting_automation'].includes(run.status)&&<Button variant="secondary" disabled={busy} onClick={()=>action('retry')}><RefreshCw size={14}/>Retry run</Button>}</div></div>
}
export function ProjectPage(){
  const {id}=useParams(), project=useApi<Project>('/projects/'+id,6000),clips=useApi<Clip[]>('/projects/'+id+'/clips',10000)
  if(!project.data)return project.error?<Alert error={project.error}/>:<Loading/>
  const p=project.data
  return <><PageHead title={p.name} sub={label(p.content_type)+' · '+date(p.created_at)} action={!p.legacy&&<Link className="btn secondary" to={'/new?project='+p.id}><CirclePlay size={16}/>Generate clips</Link>}/><div className="dash-columns"><div className="dash-main"><section className="panel"><h2>Source media</h2>{p.assets.length?p.assets.map(asset=><div key={asset.id}><video className="source-video" controls playsInline preload="metadata" src={apiBase+'/assets/'+asset.id+'/preview'}/><div className="asset-line"><strong>{asset.filename}</strong><span>{asset.width} × {asset.height} · {time(asset.duration)}</span></div></div>):<Empty title="No source attached">{p.legacy?'Source details are unavailable for this historical job.':'Open Generate clips to attach a video.'}</Empty>}</section>
  <section className="panel"><h2>Generated clips</h2><Alert error={clips.error}/>{clips.isPending?<Loading/>:clips.data?.length?clips.data.map(c=><Link className="item-link" key={c.id} to={'/editor/'+c.id}><Film size={17}/>{c.title}<Badge value={c.review.status}/><ChevronRight size={16}/></Link>):<p className="muted">No clips available yet.</p>}</section></div>
  <section className="panel"><h2>Processing history</h2>{p.runs.length?p.runs.map(r=><RunView key={r.id} initial={r}/>):<Empty title="No runs yet"/>}</section></div></>
}
export function Automation(){
  const runs=useApi<Run[]>('/runs',6000),errors=useApi<{id?:string;detail?:string;message?:string;created_at?:string}[]>('/automation/errors',15000),projects=useApi<Project[]>('/projects',30000),[active,setActive]=useState(false)
  const scan=useApi<{status:string;created_at:string;imported:string[];duplicates:number;errors:string[]} | null>('/automation/ingestion',15000)
  const test=useMutation({mutationFn:()=>api<{reachable:boolean;configured:boolean;verified:boolean;detail:string}>('/system/test-n8n','POST')})
  const filtered=(runs.data||[]).filter(r=>!active||!terminal.has(r.status))
  return <><PageHead title="Automation" sub="Monitor workflow handoffs and the local processing queue." action={<Button variant="secondary" onClick={()=>test.mutate()} disabled={test.isPending}><Radio size={16}/>Test n8n connection</Button>}/><Alert error={test.error||runs.error||errors.error}/>{test.data&&<div className="notice" role="status"><Badge value={test.data.verified?'connected':test.data.reachable?'unverified':'disconnected'}/>{test.data.detail}</div>}
  <div className="section-title"><h2>Run history</h2><label className="checkbox"><input type="checkbox" checked={active} onChange={e=>setActive(e.target.checked)}/>Active only</label></div>
  {scan.data&&<section className="panel"><div className="section-title"><h2>Latest scheduled scan</h2><Badge value={scan.data.status}/></div>
    <dl className="facts"><dt>Started</dt><dd>{date(scan.data.created_at)}</dd><dt>Imported</dt><dd>{scan.data.imported.length}</dd><dt>Duplicates</dt><dd>{scan.data.duplicates}</dd></dl>
    {scan.data.errors.map((item,index)=><p className="warning" key={index}>{item}</p>)}</section>}
  {runs.isPending?<Loading/>:filtered.length?<div className="run-grid">{filtered.map(run=><section className="panel" key={run.id}><Link className="sub-link" to={'/projects/'+run.project_id}>{projects.data?.find(p=>p.id===run.project_id)?.name||'Open project'}<ArrowUpRight size={14}/></Link><RunView initial={run}/></section>)}</div>:<Empty title="No matching runs"/>}
  <section className="panel"><h2>Workflow errors</h2>{errors.data?.length?errors.data.map((e,i)=><div key={e.id||i} className="alert">{date(e.created_at)} · {e.detail||e.message||'Workflow execution failed'}</div>):errors.isPending?<Loading/>:<p className="muted">No workflow errors recorded.</p>}</section></>
}

export function Settings(){
  const q=useApi<Health>('/system/status'),client=useQueryClient()
  const logout=useMutation({mutationFn:()=>api('/session','DELETE'),onSuccess:()=>{client.clear();void client.invalidateQueries()}})
  return <><PageHead title="Workspace settings" sub="Local services and session controls."/><Alert error={q.error||logout.error}/>{q.data?<div className="dash-columns"><section className="panel"><h2>Runtime</h2><Check name="FFmpeg" good={q.data.ffmpeg}/><Check name="FFprobe" good={q.data.ffprobe}/><Check name={'Whisper · '+q.data.whisper_model} good={q.data.whisper_model_available}/><Check name={'Ollama · '+q.data.ollama_model} good={q.data.ollama_model_available}/><div className="disk"><span>Free disk space</span><strong>{(q.data.free_disk_bytes/1024**3).toFixed(1)} GiB</strong></div></section><section className="panel"><h2>Local session</h2><p className="muted">Service addresses and model selections are configured in the workspace’s .env file.</p><Button variant="secondary" onClick={()=>logout.mutate()} disabled={logout.isPending}>Sign out</Button></section></div>:q.isPending&&<Loading/>}</>
}
