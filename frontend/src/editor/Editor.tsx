import { useRef, useState, type PointerEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useStore } from 'zustand'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Crop, Download, Play, Redo2, Save, Undo2 } from 'lucide-react'
import { Alert, Badge, Empty, Field, Loading, PageHead, useApi } from '../components/common'
import { Button } from '../components/ui/button'
import { useRender } from '../hooks/useRender'
import { ReviewControls } from '../pages/Clips'
import { api, apiBase, label, time } from '../services/http'
import type { Caption, Clip, Edit, PublishingMetadata, Region } from '../types'
import MetadataControls from './MetadataControls'
import { CaptionControls, CutControls, NumberField, StyleControls } from './Controls'
import { createHistory } from './history'

interface Timeline {
  duration:number; waveform:number[]; thumbnails:{url:string;time:number}[]
  tracks?:{id:string|number;points:{time:number;box:Region}[]}[]
}
type RegionName = 'roi'|'facecam'|'gameplay'
const names={roi:'Crop',facecam:'Facecam',gameplay:'Gameplay'}
const round=(n:number)=>Math.round(n*1000)/1000

export default function Editor() {
  const {id}=useParams()
  const q=useApi<Clip>('/clips/'+id)
  if(q.error)return <Alert error={q.error}/>
  if(!q.data)return <Loading/>
  if(!q.data.asset_id||!q.data.edit)return <Empty title="Source unavailable">This clip needs its source video to open a reversible edit.</Empty>
  return <EditWorkspace key={q.data.id+':'+q.data.revision} clip={q.data} initial={q.data.edit} assetId={q.data.asset_id}/>
}

function EditWorkspace({clip,initial,assetId}:{clip:Clip;initial:Edit;assetId:string}) {
  const [history]=useState(()=>createHistory(initial))
  const {edit,change,past,future,undo,redo}=useStore(history)
  const [regionName,setRegionName]=useState<RegionName>('roi')
  const [drawing,setDrawing]=useState(false)
  const [drag,setDrag]=useState<Region|null>(null)
  const dragOrigin=useRef<{x:number;y:number}|null>(null)
  const video=useRef<HTMLVideoElement>(null)
  const [position,setPosition]=useState(initial.start_seconds)
  const [duration,setDuration]=useState(0)
  const [ratio,setRatio]=useState(16/9)
  const [monitor,setMonitor]=useState<'source'|'preview'>('source')
  const [saving,setSaving]=useState(false)
  const [error,setError]=useState('')
  const client=useQueryClient(), task=useRender()
  const timeline=useApi<Timeline>('/assets/'+assetId+'/timeline')
  const transcript=useApi<{segments:Caption[]}>('/clips/'+clip.id+'/transcript')
  const tracks = timeline.data?.tracks?.filter(track => track.points.length >= 3) || []
  const tracking = edit.layout === 'track' || edit.layout === 'dynamic'
  const [initialMetadata] = useState<PublishingMetadata>(() => ({
    title:clip.title, hook:clip.hook, caption:clip.caption, description:clip.description, hashtags:clip.hashtags,
    instagram_caption:clip.instagram_caption || '', tiktok_caption:clip.tiktok_caption || '', thumbnail_text:clip.thumbnail_text || '',
  }))
  const [metadata, setMetadata] = useState(initialMetadata)
  const metadataChanged = JSON.stringify(initialMetadata) !== JSON.stringify(metadata)
  const editChanged = JSON.stringify(initial) !== JSON.stringify(edit)
  const changed = editChanged || metadataChanged
  const sourceDuration=duration||timeline.data?.duration||edit.end_seconds
  const activeBox=drag||edit[regionName]
  const removed=edit.cuts.reduce((sum,c)=>sum+c.end-c.start,0)
  const seek=(seconds:number)=>{
    if(video.current){video.current.currentTime=Math.max(0,Math.min(seconds,sourceDuration));setPosition(video.current.currentTime)}
  }
  function point(event:PointerEvent<HTMLElement>){
    const rect=event.currentTarget.getBoundingClientRect()
    return {x:Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),y:Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))}
  }
  function draw(event:PointerEvent<HTMLElement>,finish=false){
    const a=dragOrigin.current
    if(!a)return
    const b=point(event)
    const box={x:Math.min(a.x,b.x),y:Math.min(a.y,b.y),width:Math.abs(a.x-b.x),height:Math.abs(a.y-b.y)}
    if(finish){
      if(box.width>.006&&box.height>.006){change({[regionName]:box});setDrawing(false)}
      dragOrigin.current=null;setDrag(null)
    }else setDrag(box)
  }
  async function save() {
    setSaving(true);setError('')
    try{
      const published = metadataChanged ? {...metadata, hashtags:metadata.hashtags.map(tag=>tag.trim()).filter(Boolean)} : undefined
      await api('/clips/'+clip.id,'PATCH',{edit,revision:clip.revision,metadata:published})
      await client.invalidateQueries({queryKey:['/clips/'+clip.id]})
      await client.invalidateQueries({queryKey:['/clips']})
    }catch(err){setError((err as Error).message)}finally{setSaving(false)}
  }
  function selectLayout(layout:string){
    const useTrack = layout === 'track' || layout === 'dynamic'
    change({layout, track_id: useTrack ? edit.track_id ?? Number(tracks[0]?.id) : null})
    if(layout==='roi')setRegionName('roi')
    if(['pip','split','split_below'].includes(layout))setRegionName('facecam')
  }
  return <>
    <Link to="/clips" className="sub-link"><ArrowLeft size={15}/>Clip library</Link>
    <PageHead title={clip.title} sub={clip.project_name+' · Revision '+clip.revision} action={<div className="actions">
      <Button variant="ghost" size="icon" aria-label="Undo edit" disabled={!past.length} onClick={undo}><Undo2 size={17}/></Button>
      <Button variant="ghost" size="icon" aria-label="Redo edit" disabled={!future.length} onClick={redo}><Redo2 size={17}/></Button>
      <Button onClick={()=>void save()} disabled={saving||!changed}><Save size={16}/>Save draft</Button></div>}/>
    <Alert error={error||task.error}/>
    {task.result&&<p className="notice" role="status">{label(task.result.kind||'Render')} · {label(task.result.status)}</p>}
    <div className="editor-layout"><div className="editor-main">
      <section className="panel monitor"><div className="section-title"><h2>Monitor</h2><div className="segmented">
        <button type="button" aria-pressed={monitor==='source'} onClick={()=>setMonitor('source')}>Source</button>
        <button type="button" aria-pressed={monitor==='preview'} onClick={()=>setMonitor('preview')}>Rendered preview</button></div></div>
      {monitor==='source'?<div className="source-stage"><div className="source-frame" style={{aspectRatio:ratio,width:'min(100%, '+(ratio*52)+'vh)'}}>
        <video ref={video} playsInline controls={!drawing} preload="metadata" src={apiBase+'/assets/'+assetId+'/preview'}
          onLoadedMetadata={e=>{const v=e.currentTarget;setRatio(v.videoWidth/v.videoHeight||16/9);setDuration(v.duration);v.currentTime=initial.start_seconds}}
          onTimeUpdate={e=>setPosition(e.currentTarget.currentTime)}/>
        {activeBox&&<span className="region-box" style={{left:activeBox.x*100+'%',top:activeBox.y*100+'%',width:activeBox.width*100+'%',height:activeBox.height*100+'%'}}><b>{names[regionName]}</b></span>}
        {drawing&&<div className="draw-region" aria-label="Draw selected region" onPointerDown={e=>{dragOrigin.current=point(e);e.currentTarget.setPointerCapture(e.pointerId)}}
          onPointerUp={e=>draw(e,true)} onPointerMove={e=>draw(e)} onPointerCancel={()=>{dragOrigin.current=null;setDrag(null)}}/>}
      </div></div>:<div className="source-stage"><video key={clip.rendered_preview||clip.id} className="preview-video" playsInline controls preload="metadata" src={clip.rendered_preview||apiBase+'/clips/'+clip.id+'/media'}/></div>}
      <p className="small muted">{monitor==='source'?'Source coordinates and timing. Render a preview to check the edited picture and audio.':clip.rendered_preview?'Server-rendered preview of the saved revision.':'Initial generated clip. Render a preview to check the current draft.'}</p>
      {clip.rendered_layout==='fit' && tracking && <p className="warning">The saved render used full-frame padding because the sampled track did not cover this selection safely.</p>}
      </section>
      <section className="panel timeline"><div className="section-title"><h2>Source timeline</h2><span className="mono">{time(position,true)} / {time(sourceDuration,true)}</span></div>
        {timeline.data?.thumbnails?.length ? <div className="filmstrip">{timeline.data.thumbnails.map((t,i)=><button type="button" disabled={monitor!=='source'} key={i} aria-label={'Seek to '+time(t.time,true)} onClick={()=>seek(t.time)}><img src={t.url} alt=""/></button>)}</div>:null}
        {timeline.data?.waveform?.length ? <div className="waveform" aria-label="Source audio waveform">{timeline.data.waveform.filter((_,i,all)=>i%Math.max(1,Math.ceil(all.length/220))===0).map((v,i)=><i key={i} style={{height:Math.max(2,Math.min(100,Math.abs(v)*100))+'%'}}/>)}</div>:null}
        <Alert error={timeline.error}/>
        <Field name="Seek source"><input type="range" min={0} max={sourceDuration} step={0.001} value={position} disabled={monitor!=='source'} onChange={e=>seek(Number(e.target.value))}/></Field>
        <div className="form-grid"><Field name="Trim start handle"><input type="range" min={0} max={sourceDuration} step={.001} value={edit.start_seconds} onChange={e=>change({start_seconds:round(Math.min(Number(e.target.value),edit.end_seconds-.25))})}/></Field>
        <Field name="Trim end handle"><input type="range" min={0} max={sourceDuration} step={.001} value={edit.end_seconds} onChange={e=>change({end_seconds:round(Math.max(Number(e.target.value),edit.start_seconds+.25))})}/></Field>
        <NumberField name="Source in (seconds)" min={0} max={sourceDuration} value={edit.start_seconds} onChange={v=>change({start_seconds:v})}/>
        <NumberField name="Source out (seconds)" min={0} max={sourceDuration} value={edit.end_seconds} onChange={v=>change({end_seconds:v})}/></div>
        <p className="small muted">Edited duration · {time(Math.max(0,edit.end_seconds-edit.start_seconds-removed),true)}</p>
        <CutControls edit={edit} change={change} position={position}/></section>
      <section className="panel"><div className="section-title"><h2>Review and export</h2><Badge value={clip.review.status}/></div>
        <div className="actions"><Button variant="secondary" disabled={changed||task.busy} onClick={()=>void task.start('/clips/'+clip.id+'/preview')}><Play size={15}/>Render preview</Button>
        <Button disabled={changed||task.busy||clip.review.status!=='approved'} onClick={()=>void task.start('/clips/'+clip.id+'/render')}><Download size={15}/>Export final</Button>
        {clip.exported&&clip.review.status==='approved'&&<a className="sub-link" href={apiBase+'/clips/'+clip.id+'/download'} download>Download final MP4</a>}</div>
        {changed?<p className="warning">Save this draft before reviewing or rendering.</p>:<ReviewControls clip={clip}/>}</section>
    </div><section className="panel inspector"><h2>Edit settings</h2>
      <details open><summary>Framing</summary><Field name="Vertical layout"><select value={edit.layout} onChange={e=>selectLayout(e.target.value)}>{
        Object.entries({fit:'Full frame with padding',blur:'Blurred background',crop:'Center crop',roi:'Manual crop',split:'Facecam above',split_below:'Facecam below',pip:'Picture-in-picture',track:'Follow tracked face',dynamic:'Switch between full frame and tracked face'}).map(([k,n])=><option value={k} key={k} disabled={['track','dynamic'].includes(k) && !tracks.length}>{n}</option>)}</select></Field>
        {tracking && <Field name="Primary face track"><select value={edit.track_id ?? ''} onChange={e=>change({track_id:Number(e.target.value)})}>
          {tracks.map(track => <option key={track.id} value={track.id}>Track {track.id}</option>)}
        </select></Field>}
        <Field name="Region to edit"><select value={regionName} onChange={e=>setRegionName(e.target.value as RegionName)}>{Object.entries(names).map(([k,n])=><option key={k} value={k}>{n}</option>)}</select></Field>
        <Button variant="secondary" size="small" onClick={()=>{setMonitor('source');setDrawing(!drawing)}}><Crop size={15}/>{drawing?'Cancel drawing':'Draw region on source'}</Button>
        {drawing&&<p className="small muted">Drag between two corners of the region on the source monitor.</p>}
        <div className="form-grid">{(['x','y','width','height'] as const).map(k=><NumberField key={k} name={names[regionName]+' '+k+' (%)'} min={0} max={100} value={round((edit[regionName]?.[k]??(k==='width'||k==='height'?1:0))*100)} onChange={v=>change({[regionName]:{x:0,y:0,width:1,height:1,...edit[regionName],[k]:v/100}})}/>)}</div>
        {!!timeline.data?.tracks?.length&&<Field name="Use tracked face at playhead"><select value="" onChange={e=>{
          const track=timeline.data?.tracks?.find(t=>String(t.id)===e.target.value)
          const nearest=track?.points.reduce((a,b)=>Math.abs(a.time-position)<Math.abs(b.time-position)?a:b)
          if(nearest)change({[regionName]:nearest.box})
        }}><option value="">Choose a track</option>{timeline.data.tracks.filter(t=>t.points.length>0).map(t=><option key={t.id} value={t.id}>Track {t.id}</option>)}</select></Field>}</details>
      <StyleControls edit={edit} change={change}/>
      <MetadataControls clipId={clip.id} revision={clip.revision} value={metadata} onChange={setMetadata} hasUnsavedEdit={editChanged}/>
      {!!clip.hook_options?.length&&<Field name="Suggested hook"><select value="" onChange={e=>change({hook:e.target.value})}><option value="">Choose an option</option>{clip.hook_options.map(h=><option key={h}>{h}</option>)}</select></Field>}
      <CaptionControls edit={edit} change={change} position={position} sourceCues={transcript.data?.segments}/>
      <Alert error={transcript.error}/>
    </section></div></>
}

