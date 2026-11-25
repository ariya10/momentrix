import { Plus, Trash2 } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Field } from '../components/common'
import type { Edit, Span } from '../types'

export function NumberField({name,value,onChange,min=0,max,step=0.001}: {
  name:string; value:number; onChange:(v:number)=>void; min?:number; max?:number; step?:number
}) {
  return <Field name={name}><input type="number" value={value} min={min} max={max} step={step}
    onChange={e=>{if(Number.isFinite(e.target.valueAsNumber))onChange(e.target.valueAsNumber)}}/></Field>
}

export function CutControls({edit, change, position}: {edit:Edit;change:(p:Partial<Edit>)=>void;position:number}) {
  function patch(i:number,p:Partial<Span>){change({cuts:edit.cuts.map((v,k)=>k===i?{...v,...p}:v)})}
  const start=Math.max(edit.start_seconds,position,edit.cuts.at(-1)?.end||0)
  return <details><summary>Jump cuts</summary><p className="muted">Remove source intervals. Captions follow the remaining audio.</p>
    {edit.cuts.map((cut,i)=><div className="interval" key={i}>
      <NumberField name={'Cut '+(i+1)+' start'} value={cut.start} onChange={v=>patch(i,{start:v})}/>
      <NumberField name={'Cut '+(i+1)+' end'} value={cut.end} onChange={v=>patch(i,{end:v})}/>
      <Button variant="ghost" size="icon" aria-label={'Remove cut '+(i+1)} onClick={()=>change({cuts:edit.cuts.filter((_,k)=>k!==i)})}><Trash2 size={15}/></Button>
    </div>)}
    <Button size="small" variant="secondary" disabled={edit.cuts.length>=32||start>=edit.end_seconds-0.25}
      onClick={()=>change({cuts:[...edit.cuts,{start,end:Math.min(start+0.5,edit.end_seconds)}]})}><Plus size={14}/>Cut at playhead</Button>
  </details>
}

export function StyleControls({edit,change}:{edit:Edit;change:(p:Partial<Edit>)=>void}) {
  return <><details open><summary>Subtitles</summary>
    <div className="form-grid"><Field name="Caption style"><select value={edit.subtitle_style} onChange={e=>change({subtitle_style:e.target.value})}>
      {Object.entries({standard:'Standard white',word:'Word highlight',karaoke:'Karaoke',yellow:'Yellow emphasis',gaming:'Gaming',minimal:'Minimal',none:'None'}).map(([v,n])=><option key={v} value={v}>{n}</option>)}</select></Field>
    <Field name="Position"><select value={edit.subtitle_position} onChange={e=>change({subtitle_position:e.target.value})}>{['bottom','middle','top'].map(v=><option key={v}>{v}</option>)}</select></Field>
    <Field name="Font"><input value={edit.subtitle_font} maxLength={50} onChange={e=>change({subtitle_font:e.target.value})}/></Field>
    <NumberField name="Font size" value={edit.subtitle_size} min={18} max={110} step={1} onChange={v=>change({subtitle_size:v})}/>
    <Field name="Text colour"><input type="color" value={edit.subtitle_color} onChange={e=>change({subtitle_color:e.target.value})}/></Field>
    <Field name="Highlight colour"><input type="color" value={edit.highlight_color} onChange={e=>change({highlight_color:e.target.value})}/></Field>
    <NumberField name="Outline" value={edit.subtitle_outline??3} max={12} step={1} onChange={v=>change({subtitle_outline:v})}/>
    <NumberField name="Safe margin" value={edit.safe_margin??140} min={30} max={400} step={1} onChange={v=>change({safe_margin:v})}/>
    <NumberField name="Maximum lines" value={edit.max_lines??2} min={1} max={3} step={1} onChange={v=>change({max_lines:v})}/></div>
    <label className="checkbox"><input type="checkbox" checked={edit.subtitle_background??false} onChange={e=>change({subtitle_background:e.target.checked})}/>Caption background</label>
  </details>
  <details><summary>Opening hook</summary><Field name="Hook text"><textarea value={edit.hook} maxLength={120} onChange={e=>change({hook:e.target.value})}/></Field>
    <div className="form-grid"><NumberField name="Hook seconds" value={edit.hook_seconds} min={0.1} max={10} onChange={v=>change({hook_seconds:v})}/>
    <Field name="Hook position"><select value={edit.hook_position??'top'} onChange={e=>change({hook_position:e.target.value})}>{['top','middle','bottom'].map(v=><option key={v}>{v}</option>)}</select></Field></div></details>
  <details><summary>Audio and output</summary>
    {([['normalize_audio','Normalize audio'],['denoise','Light noise reduction'],['fade_in','Fade in']] as const).map(([key,name])=><label className="checkbox" key={key}><input type="checkbox" checked={edit[key]} onChange={e=>change({[key]:e.target.checked})}/>{name}</label>)}
    <div className="form-grid"><Field name="Export resolution"><select value={edit.resolution} onChange={e=>change({resolution:Number(e.target.value)})}><option value={1080}>1080 × 1920</option><option value={720}>720 × 1280</option></select></Field>
    <Field name="Frame rate"><select value={edit.fps} onChange={e=>change({fps:Number(e.target.value)})}>{[24,25,30,50,60].map(n=><option value={n} key={n}>{n} fps</option>)}</select></Field></div></details></>
}

export function CaptionControls({edit,change,position,sourceCues}:{edit:Edit;change:(p:Partial<Edit>)=>void;position:number;sourceCues?:Edit['captions']}) {
  const captions=edit.captions
  const start=Math.max(edit.start_seconds,position,captions?.at(-1)?.end||0)
  return <details><summary>Transcript corrections</summary>
    {captions===null?<><p className="muted">The render uses the source word timings. Manual cues replace automatic captions for this edit.</p><Button variant="secondary" size="small" onClick={()=>change({captions:sourceCues?.filter(c=>c.end>edit.start_seconds&&c.start<edit.end_seconds)||[]})}>Edit timed captions</Button></>:<>
      {captions.map((cue,i)=>{
        const revise=(patch:Partial<typeof cue>)=>change({captions:captions.map((c,k)=>i===k?{...c,...patch}:c)})
        return <div className="cue" key={i}><div className="interval"><NumberField name={'Cue '+(i+1)+' start'} value={cue.start} onChange={start=>revise({start})}/><NumberField name={'Cue '+(i+1)+' end'} value={cue.end} onChange={end=>revise({end})}/>
        <Button variant="ghost" size="icon" aria-label={'Remove cue '+(i+1)} onClick={()=>change({captions:captions.filter((_,k)=>i!==k)})}><Trash2 size={15}/></Button></div>
        <Field name={'Cue '+(i+1)+' text'}><input value={cue.text} maxLength={450} onChange={e=>revise({text:e.target.value})}/></Field></div>
      })}
      <div className="actions"><Button size="small" variant="secondary" disabled={start>=edit.end_seconds} onClick={()=>change({captions:[...captions,{start,end:Math.min(start+2,edit.end_seconds),text:''}]})}><Plus size={14}/>Add cue</Button>
      <Button size="small" variant="ghost" onClick={()=>change({captions:null})}>Use source captions</Button></div></>}
  </details>
}

