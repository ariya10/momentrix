import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Check, Clock3, Download, FileCheck2, Film, ListFilter, Pencil, Search, X } from 'lucide-react'
import { Alert, Badge, Empty, Field, Loading, PageHead, useApi } from '../components/common'
import { Button } from '../components/ui/button'
import { useRender } from '../hooks/useRender'
import { api, apiBase, label, time } from '../services/http'
import type { Clip } from '../types'

export function ReviewControls({clip}:{clip:Clip}){
  const client=useQueryClient(),[note,setNote]=useState(clip.review.note||''),[error,setError]=useState(''),[busy,setBusy]=useState(false)
  async function review(status:string){
    setBusy(true);setError('')
    try{await api('/clips/'+clip.id+'/review','POST',{status,note,revision:clip.revision});await client.invalidateQueries()}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  return <div className="review-controls"><Field name="Reviewer notes"><textarea value={note} rows={2} maxLength={1500} onChange={e=>setNote(e.target.value)} placeholder="Reasons or corrections for this clip"/></Field><Alert error={error}/><div className="actions"><Button variant="secondary" size="small" disabled={busy} onClick={()=>review('approved')}><Check size={15}/>Approve</Button><Button variant="ghost" size="small" disabled={busy} onClick={()=>review('rejected')}><X size={15}/>Reject</Button></div></div>
}
export function ClipLibrary({selectForEdit=false}:{selectForEdit?:boolean}){
  const clips=useApi<Clip[]>('/clips',20000),[search,setSearch]=useState(''),[project,setProject]=useState(''),[campaign,setCampaign]=useState(''),[review,setReview]=useState(''),[sort,setSort]=useState('score'),[selected,setSelected]=useState<string[]>([]),task=useRender()
  const all=clips.data||[]
  const results=all.filter(c=>(!project||c.project_id===project)&&(!campaign||c.campaign===campaign)&&(!review||c.review.status===review)&&(c.title+' '+c.category+' '+c.project_name).toLowerCase().includes(search.toLowerCase())).sort((a,b)=>sort==='duration'?b.duration-a.duration:b.score-a.score)
  const eligible=selected.filter(id=>all.some(c=>c.id===id&&c.review.status==='approved'))
  return <><PageHead title={selectForEdit?'Video editor':'Clip library'} sub={selectForEdit?'Select a generated clip to open its timeline.':'Preview, review, and export clips from your projects.'} action={!selectForEdit&&<Button disabled={!eligible.length||task.busy} onClick={()=>void task.start('/exports',{clip_ids:eligible})}><Download size={16}/>Export selected{eligible.length?' ('+eligible.length+')':''}</Button>}/>
    <div className="filters"><label className="search"><Search size={16}/><input aria-label="Search clips" placeholder="Search clips" value={search} onChange={e=>setSearch(e.target.value)}/></label>
    <select aria-label="Filter by project" value={project} onChange={e=>setProject(e.target.value)}><option value="">All projects</option>{Array.from(new Map(all.map(c=>[c.project_id,c.project_name]))).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select>
    <select aria-label="Filter by campaign" value={campaign} onChange={e=>setCampaign(e.target.value)}><option value="">All campaigns</option>{Array.from(new Set(all.map(c=>c.campaign))).map(v=><option value={v} key={v}>{v}</option>)}</select>
    <select aria-label="Filter review status" value={review} onChange={e=>setReview(e.target.value)}><option value="">All review states</option>{['pending','approved','rejected'].map(v=><option value={v} key={v}>{label(v)}</option>)}</select><select value={sort} aria-label="Sort clips" onChange={e=>setSort(e.target.value)}><option value="score">Highest score</option><option value="duration">Longest first</option></select></div>
    <Alert error={clips.error||task.error}/>{task.result&&<div className="notice" role="status">Export · {label(task.result.status)}</div>}{clips.isPending?<Loading/>:!results.length?<Empty title="No matching clips">Generated clips appear here when processing finishes.</Empty>:<div className="clip-grid">{results.map(c=><article className="clip-card" key={c.id}><div className="clip-video"><video controls preload="metadata" playsInline src={apiBase+'/clips/'+c.id+'/media#t=0.1'}/></div><div className="clip-body"><div className="clip-meta"><span>{c.category}</span><Badge value={c.review.status}/></div><h3>{c.title}</h3><Link className="sub-link" to={'/projects/'+c.project_id}>{c.project_name}</Link><div className="clip-facts"><span><Clock3 size={14}/>{time(c.duration)}</span><span><ListFilter size={14}/>{c.score}/100</span><span><FileCheck2 size={14}/>{c.exported?'Exported':'Preview'}</span></div><p className="small muted">Campaign · {c.campaign}</p><Link className="btn secondary small" to={'/editor/'+c.id}><Pencil size={14}/>Open editor</Link>
    {!selectForEdit&&<><details><summary>Evidence and review</summary><p>{c.selection_reason}</p>{c.supporting_transcript&&<blockquote>{c.supporting_transcript}</blockquote>}{c.evidence?.map((ev,i)=><p className="small muted" key={i}>{time(ev.start,true)}?{time(ev.end,true)} ? {label(ev.signal)} ? {ev.detail}</p>)}<dl className="facts">{Object.entries(c.component_scores||c.score_breakdown||{}).map(([s,v])=><div key={s} className="fact-pair"><dt>{label(s)}</dt><dd>{c.component_scores?Math.round(v*100)+'%':v}</dd></div>)}</dl>{c.review_flags?.map(f=><p key={f} className="warning">{f}</p>)}<ReviewControls clip={c}/></details>
    {c.review.status==='approved'&&<label className="checkbox"><input type="checkbox" checked={eligible.includes(c.id)} onChange={e=>setSelected(prev=>e.target.checked?[...prev,c.id]:prev.filter(id=>id!==c.id))}/>Select for export</label>}{c.exported&&c.review.status==='approved'&&<a className="sub-link" href={apiBase+'/clips/'+c.id+'/download'} download><Download size={15}/>Download final clip</a>}</>}</div></article>)}</div>}</>
}
