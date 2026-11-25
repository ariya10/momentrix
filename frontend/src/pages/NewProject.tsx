import { useRef, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, Check, ChevronRight, Clapperboard, FileVideo, FolderOpen, Play, UploadCloud } from 'lucide-react'
import { Alert, Field, Loading, PageHead, useApi } from '../components/common'
import { Button } from '../components/ui/button'
import { api, label, time, uploadFile } from '../services/http'
import type { Asset, Campaign, Health, Project, Run } from '../types'

const steps=['Source video','Content type','Campaign','Generation','Editing style','Start automation']
const contentTypes=['gaming','livestream','podcast','interview','reaction','educational','general']
const presets = {
  fast: 'Samples fewer frames and uses a quicker Whisper search and encode.',
  balanced: 'Uses the standard analysis, transcription, and encoding settings.',
  quality: 'Samples more frames, searches more Whisper alternatives, and encodes at higher quality.',
}
type ProcessingPreset = keyof typeof presets
const nameFor=(file:string)=>file.replace(/\.[^.]+$/,'').replace(/[_-]+/g,' ').trim()

export default function NewProject(){
  const [search]=useSearchParams()
  return <Wizard key={search.toString()} existingId={search.get('project')}/>
}
function Wizard({existingId}:{existingId:string|null}){
  const navigate=useNavigate(),client=useQueryClient(),sources=useApi<string[]>('/sources'),campaigns=useApi<Campaign[]>('/campaigns'),projects=useApi<Project[]>('/projects'),health=useApi<Health>('/system/status')
  const existing=projects.data?.find(p=>p.id===existingId)
  const [step,setStep]=useState(0),[name,setName]=useState(''),[mode,setMode]=useState<'upload'|'local'>('upload'),[file,setFile]=useState<File|null>(null),[filename,setFilename]=useState(''),[authorized,setAuthorized]=useState(false),[content,setContent]=useState('general')
  const [campaignId,setCampaign]=useState('default'),[count,setCount]=useState(3),[minimum,setMinimum]=useState(20),[maximum,setMaximum]=useState(60),[layout,setLayout]=useState('fit'),[subtitles,setSubtitles]=useState(true),[position,setPosition]=useState('bottom'),[hook,setHook]=useState(false),[normalize,setNormalize]=useState(false)
  const [preset, setPreset] = useState<ProcessingPreset>('balanced')
  const [error,setError]=useState(''),[saving,setSaving]=useState(false),[progress,setProgress]=useState<number|null>(null),[phase,setPhase]=useState(''),[dragging,setDragging]=useState(false)
  const fileInput=useRef<HTMLInputElement>(null),projectRef=useRef<string|null>(existingId),assetRef=useRef<Asset|null>(null),idempotency=useRef(crypto.randomUUID())
  const campaign=campaigns.data?.find(c=>c.id===campaignId),asset=assetRef.current||existing?.assets[0]
  const source=asset?.filename||(mode==='local'?filename:file?.name)||'', projectName=existing?.name||name.trim()||nameFor(source)
  function setSource(f:File|undefined){
    setError('');if(!f)return
    if(!/\.(mp4|mov|mkv|webm)$/i.test(f.name)||!f.size){setError('Choose a nonempty MP4, MOV, MKV, or WebM video.');return}
    if(health.data?.max_input_bytes && f.size>health.data.max_input_bytes){setError('The video exceeds the configured upload size limit.');return}
    setFile(f)
  }
  function changeCampaign(id:string){
    setCampaign(id)
    const next=campaigns.data?.find(c=>c.id===id)
    if(next){setMinimum(next.min_duration);setMaximum(next.max_duration);setLayout(next.layout);setCount(Math.min(next.count,20))}
  }
  async function submit(e:FormEvent){
    e.preventDefault();setError('')
    if(step===0 && (!authorized||!source||!projectName)){setError('Select a source video and confirm permission before continuing.');return}
    if(step===3 && (minimum>maximum||!campaign||minimum<campaign.min_duration||maximum>campaign.max_duration)){setError('Choose ordered clip durations inside the selected campaign range.');return}
    if(step<5){setStep(step+1);return}
    if(saving)return
    setSaving(true)
    try{
      let id=projectRef.current
      if(!id){
        setPhase('Saving project…');const project=await api<Project>('/projects','POST',{name:projectName,content_type:content,authorized:true})
        id=project.id;projectRef.current=id
      }
      let chosen=asset
      if(!chosen){
        setPhase(mode==='upload'?'Uploading and inspecting source…':'Inspecting local source…')
        const endpoint = '/projects/' + id + '/assets?processing_preset=' + preset
        if(mode==='upload'&&file){setProgress(0);chosen=await uploadFile<Asset>(endpoint,file,setProgress)}
        else chosen=await api<Asset>(endpoint,'POST',{filename})
        assetRef.current=chosen
      }
      setPhase('Starting automation…')
      await api<Run>('/projects/'+id+'/generate','POST',{asset_id:chosen.id,idempotency_key:idempotency.current,options:{campaign:campaignId,count,min_duration:minimum,max_duration:maximum,layout,processing_preset:preset,subtitles,subtitle_position:position,opening_hook:hook,normalize_audio:normalize}})
      await client.invalidateQueries({queryKey:['/projects']})
      navigate('/projects/'+id)
    }catch(err){setError((err as Error).message)}finally{setSaving(false);setProgress(null);setPhase('')}
  }
  if(existingId && !existing)return projects.isPending?<Loading/>:<Alert error={projects.error||'This project could not be found.'}/>
  return <><PageHead title={existing?'Generate clips':'New project'} sub={existing?existing.name:'Configure a source and send it to the generation workflow.'}/><div className="wizard-wrap"><ol className="wizard-steps" aria-label="Project creation steps">{steps.map((title,i)=><li key={title} className={i===step?'current':i<step?'done':''} aria-current={i===step?'step':undefined}><span>{i<step?<Check size={14}/>:i+1}</span>{title}</li>)}</ol>
    <form className="panel wizard" onSubmit={submit}><div className="section-title"><h2>{steps[step]}</h2><small>{step+1} / {steps.length}</small></div>
    {step===0&&<>
    {asset?<div className="selected-source"><FileVideo size={22}/><div><strong>{asset.filename}</strong><small>{asset.width} × {asset.height} · {time(asset.duration)}</small></div></div>:<>
      <div className="segmented"><button type="button" aria-pressed={mode==='upload'} onClick={()=>setMode('upload')}><UploadCloud size={16}/>Upload video</button><button type="button" aria-pressed={mode==='local'} onClick={()=>setMode('local')}><FolderOpen size={16}/>Local folder</button></div>
      {mode==='upload'? <><input ref={fileInput} type="file" hidden accept=".mp4,.mov,.mkv,.webm" aria-label="Select source video" onChange={e=>setSource(e.target.files?.[0])}/><button className={'drop-zone '+(dragging?'drag':'')} type="button" onClick={()=>fileInput.current?.click()} onDragOver={e=>{e.preventDefault();setDragging(true)}} onDragLeave={()=>setDragging(false)} onDrop={e=>{e.preventDefault();setDragging(false);setSource(e.dataTransfer.files[0])}}><UploadCloud size={32} strokeWidth={1.4}/><strong>{file?file.name:'Choose a video or drop it here'}</strong><small>{file?(file.size/1024**2).toFixed(1)+' MiB':'MP4, MOV, MKV, or WebM'}</small></button></>:<Field name="Authorized file in input/"><select value={filename} onChange={e=>setFilename(e.target.value)}><option value="">Choose a local video</option>{sources.data?.map(s=><option key={s}>{s}</option>)}</select></Field>}
    </>}
    {!existing&&<Field name="Project name"><input maxLength={120} placeholder={source?nameFor(source):'Name your project'} value={name} onChange={e=>setName(e.target.value)}/></Field>}
    <label className="checkcard"><input type="checkbox" checked={authorized} onChange={e=>setAuthorized(e.target.checked)}/><span>I have permission to use and edit this source video.</span></label></>}
    {step===1&&<Field name="Content type"><select value={existing?.content_type||content} disabled={!!existing} onChange={e=>setContent(e.target.value)}>{contentTypes.map(c=><option value={c} key={c}>{label(c)}</option>)}</select></Field>}
    {step===2&&<><Field name="Campaign preset"><select value={campaignId} onChange={e=>changeCampaign(e.target.value)}>{campaigns.data?.filter(c=>!c.archived).map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select></Field>{campaign&&<div className="rule-box"><strong>{campaign.name}</strong><p>{campaign.min_duration}–{campaign.max_duration} seconds · {campaign.language||'Any language'}</p>{[...campaign.required_hashtags,...campaign.hook_requires,...campaign.required_keywords].map((rule,i)=><span className="tag" key={i}>{rule}</span>)}</div>}<Link to="/campaigns" target="_blank" className="sub-link">Manage custom campaigns <ChevronRight size={14}/></Link></>}
    {step===3&&<><Field name="Desired clip count"><input required type="number" min="1" max="20" value={count} onChange={e=>setCount(Number(e.target.value))}/></Field><div className="form-grid"><Field name="Minimum seconds"><input required type="number" min={campaign?.min_duration||3} max={campaign?.max_duration||180} value={minimum} onChange={e=>setMinimum(Number(e.target.value))}/></Field><Field name="Maximum seconds"><input required type="number" min={minimum} max={campaign?.max_duration||180} value={maximum} onChange={e=>setMaximum(Number(e.target.value))}/></Field></div>
      <Field name="Processing preset"><select value={preset} onChange={e=>setPreset(e.target.value as ProcessingPreset)} aria-describedby="preset-help">
        {Object.keys(presets).map(value => <option key={value} value={value}>{label(value)}</option>)}
      </select></Field>
      <p id="preset-help" className="muted">{presets[preset]}</p>
      {health.data&&<div className="rule-box">Local models · {health.data.whisper_model} / {health.data.ollama_model}</div>}</>}
    {step===4&&<><Field name="Vertical layout"><select value={layout} onChange={e=>setLayout(e.target.value)}><option value="fit">Full frame with padding</option><option value="crop">Center crop</option><option value="auto_split">Automatic facecam</option></select></Field><label className="checkbox"><input type="checkbox" checked={subtitles} onChange={e=>setSubtitles(e.target.checked)}/>Burn in subtitles</label>{subtitles&&<Field name="Subtitle position"><select value={position} onChange={e=>setPosition(e.target.value)}>{['bottom','middle','top'].map(v=><option value={v} key={v}>{label(v)}</option>)}</select></Field>}<label className="checkbox"><input type="checkbox" checked={hook} onChange={e=>setHook(e.target.checked)}/>Opening text hook</label><label className="checkbox"><input type="checkbox" checked={normalize} onChange={e=>setNormalize(e.target.checked)}/>Normalize audio</label></>}
    {step===5&&<><div className="selected-source"><Clapperboard size={25}/><div><strong>{projectName}</strong><small>{source}</small></div></div><dl className="facts"><dt>Content</dt><dd>{label(existing?.content_type||content)}</dd><dt>Campaign</dt><dd>{campaign?.name||campaignId}</dd><dt>Requested clips</dt><dd>{count} · {minimum}–{maximum}s</dd><dt>Layout</dt><dd>{label(layout)}</dd></dl><p className="muted">The local worker processes this project in the background. Review its clips before exporting.</p></>}
    <Alert error={error||sources.error||campaigns.error}/>{saving&&<div role="status" className="transfer"><span>{phase}</span>{progress!==null&&<progress value={progress} max={1} aria-label="Source upload progress"/>}</div>}
    {projectRef.current&&error&&<Link className="sub-link" to={'/projects/'+projectRef.current}>Open saved project <ChevronRight size={14}/></Link>}
    <div className="wizard-actions">{step>0&&<Button variant="ghost" disabled={saving} onClick={()=>setStep(step-1)}><ArrowLeft size={16}/>Back</Button>}<Button type="submit" disabled={saving||campaigns.isPending||!!campaigns.error}>{step===5?<><Play size={16}/>Start automation</>:<>Continue<ArrowRight size={16}/></>}</Button></div></form></div></>
}
