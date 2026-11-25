import { useRef, useState, type FormEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Archive, Copy, Download, FileUp, Flag, Pencil, Plus, Save, X } from 'lucide-react'
import { Alert, Empty, Field, Loading, PageHead, useApi } from '../components/common'
import { Button } from '../components/ui/button'
import { api } from '../services/http'
import type { Campaign } from '../types'

const fresh=():Campaign=>({id:'',name:'',creator:'',category:'General entertainment',language:null,min_duration:20,max_duration:60,preferred_min:30,preferred_max:45,count:3,required_keywords:[],required_hashtags:[],hook_requires:[],caption_requires:[],prohibited_content:[],manual_review:[],layout:'fit',authorization_required:true,archived:false,platform:'',date_start:null,date_end:null})
const lists={required_keywords:'Required spoken keywords',required_hashtags:'Required hashtags',hook_requires:'Required hook references',caption_requires:'Required caption references',prohibited_content:'Prohibited content',manual_review:'Manual review rules'}
function exportPreset(item:Campaign){
  const url=URL.createObjectURL(new Blob([JSON.stringify(item,null,2)],{type:'application/json'})),anchor=document.createElement('a')
  anchor.href=url;anchor.download=item.id+'.json';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
export function Campaigns(){
  const q=useApi<Campaign[]>('/campaigns'),client=useQueryClient()
  const [draft,setDraft]=useState<Campaign|null>(null),[existing,setExisting]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[archived,setArchived]=useState(false)
  const upload=useRef<HTMLInputElement>(null)
  function edit(campaign:Campaign,update=false){setError('');setNotice('');setExisting(update);setDraft({...campaign})}
  function change<K extends keyof Campaign>(key:K,value:Campaign[K]){if(draft)setDraft({...draft,[key]:value})}
  async function save(e:FormEvent){
    e.preventDefault();if(!draft)return
    setBusy(true);setError('')
    try{
      const {id,...body}=draft
      await api('/campaigns'+(existing?'/'+encodeURIComponent(id):''),existing?'PATCH':'POST',existing?body:{...body,...(id&&{id})})
      await client.invalidateQueries({queryKey:['/campaigns']});setDraft(null);setNotice('Campaign saved.')
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function archive(c:Campaign){
    setBusy(true);setError('')
    try{await api('/campaigns/'+c.id,'PATCH',{archived:!c.archived});await client.invalidateQueries({queryKey:['/campaigns']});setNotice(c.archived?'Campaign restored.':'Campaign archived.')}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function importFile(file?:File){
    if(!file)return
    try{
      if(file.size>256*1024)throw new Error('Campaign JSON must be smaller than 256 KiB.')
      const data=JSON.parse(await file.text())
      if(!data || typeof data.name!=='string')throw new Error('Campaign JSON requires a name.')
      for(const key of Object.keys(lists))if(data[key]!==undefined&&(!Array.isArray(data[key])||!data[key].every((v:unknown)=>typeof v==='string')))throw new Error('Campaign rule fields must be lists of text.')
      const cleaned=Object.fromEntries(Object.keys(fresh()).filter(k=>data[k]!==undefined).map(k=>[k,data[k]]))
      edit({...fresh(),...cleaned,id:'',archived:false})
    }catch(e){setError((e as Error).message)}
    finally{if(upload.current)upload.current.value=''}
  }
  return <><PageHead title="Campaigns" sub="Configure clip requirements and the checks reviewers need to make." action={<div className="actions"><Button variant="secondary" onClick={()=>upload.current?.click()}><FileUp size={16}/>Import JSON</Button><Button onClick={()=>edit(fresh())}><Plus size={16}/>New campaign</Button></div>}/>
    <input ref={upload} type="file" accept=".json,application/json" hidden onChange={e=>void importFile(e.target.files?.[0])}/><Alert error={error||q.error}/>{notice&&<p className="notice" role="status">{notice}</p>}
    {draft&&<form className="panel campaign-editor" onSubmit={save}><div className="section-title"><h2>{existing?'Edit campaign':'New campaign'}</h2><Button variant="ghost" size="icon" aria-label="Close campaign editor" onClick={()=>setDraft(null)}><X size={17}/></Button></div>
    <div className="form-grid"><Field name="Campaign name"><input required maxLength={120} value={draft.name} onChange={e=>change('name',e.target.value)}/></Field><Field name="Campaign ID"><input disabled={existing} pattern="[a-z0-9_]+" placeholder="Generated if left blank" value={draft.id} onChange={e=>change('id',e.target.value)}/></Field><Field name="Creator"><input value={draft.creator} onChange={e=>change('creator',e.target.value)}/></Field><Field name="Category"><input required value={draft.category} onChange={e=>change('category',e.target.value)}/></Field><Field name="Language code"><input pattern="[a-z]{2,3}" placeholder="Any language" value={draft.language||''} onChange={e=>change('language',e.target.value||null)}/></Field><Field name="Platform"><input value={draft.platform||''} onChange={e=>change('platform',e.target.value)}/></Field>
    {(['min_duration','max_duration','preferred_min','preferred_max','count'] as const).map((key,i)=><Field name={['Minimum seconds','Maximum seconds','Preferred minimum seconds','Preferred maximum seconds','Requested clips'][i]} key={key}><input required type="number" min={key==='count'?1:3} max={key==='count'?20:180} value={draft[key]} onChange={e=>change(key,Number(e.target.value))}/></Field>)}
    <Field name="Preferred layout"><select value={draft.layout} onChange={e=>change('layout',e.target.value)}><option value="fit">Full frame</option><option value="crop">Center crop</option><option value="auto_split">Automatic facecam</option></select></Field>
    {(['date_start','date_end'] as const).map((key,i)=><Field name={i?'Allowed through':'Allowed from'} key={key}><input type="date" value={draft[key]||''} onChange={e=>change(key,e.target.value||null)}/></Field>)}</div>
    <div className="form-grid">{(Object.keys(lists) as (keyof typeof lists)[]).map(k=><Field key={k} name={lists[k]}><textarea rows={2} placeholder="One rule per line" value={draft[k].join('\n')} onChange={e=>change(k,e.target.value.split('\n'))} onBlur={()=>change(k,draft[k].map(s=>s.trim()).filter(Boolean))}/></Field>)}</div><Button type="submit" disabled={busy}><Save size={16}/>Save campaign</Button></form>}
    <div className="section-title"><h2>Campaign presets</h2><label className="checkbox"><input type="checkbox" checked={archived} onChange={e=>setArchived(e.target.checked)}/>Show archived</label></div>
    {q.isPending?<Loading/>:<div className="campaign-grid">{q.data?.filter(c=>archived||!c.archived).map(c=><article className="panel campaign-card" key={c.id}><span className="feature-icon"><Flag size={21}/></span><h3>{c.name}</h3><p>{c.category}</p><div className="tags"><span className="tag">{c.min_duration}–{c.max_duration}s</span>{c.language&&<span className="tag">{c.language.toUpperCase()}</span>}{c.archived&&<span className="tag">Archived</span>}{c.required_hashtags.map(tag=><span className="tag" key={tag}>{tag}</span>)}</div><div className="card-actions"><Button variant="secondary" size="small" onClick={()=>edit(c,true)}><Pencil size={14}/>Edit</Button><Button variant="ghost" size="icon" title="Clone campaign" aria-label={'Clone '+c.name} onClick={()=>edit({...c,id:'',name:c.name+' copy',archived:false})}><Copy size={16}/></Button><Button variant="ghost" size="icon" title="Export JSON" aria-label={'Export '+c.name} onClick={()=>exportPreset(c)}><Download size={16}/></Button><Button variant="ghost" size="icon" disabled={busy} title={c.archived?'Restore campaign':'Archive campaign'} aria-label={(c.archived?'Restore ':'Archive ')+c.name} onClick={()=>void archive(c)}><Archive size={16}/></Button></div></article>)}</div>}
    {q.data?.length===0&&<Empty title="No campaigns yet"/>}</>
}
