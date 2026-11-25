import { ArrowDownRight, CheckCheck, Clapperboard } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Alert, Empty, Loading, PageHead, useApi } from '../components/common'
import { Stat } from './WorkspacePages'
import { label, time } from '../services/http'
import type { Metrics } from '../types'

export default function Analytics(){
  const q=useApi<Metrics>('/system/metrics',20000),m=q.data
  if(!m)return q.error?<Alert error={q.error}/>:<Loading/>
  const reviewed=m.approved_clips+m.rejected_clips
  return <><PageHead title="Workspace analytics" sub="Measured production and review activity on this machine."/><div className="stat-grid"><Stat name="Completed projects" value={m.completed_projects} Icon={CheckCheck}/><Stat name="Failed jobs" value={m.failed_jobs} Icon={ArrowDownRight}/><Stat name="Exported clips" value={m.exported_clips} Icon={Clapperboard}/><Stat name="Approval rate" value={reviewed?Math.round(100*m.approved_clips/reviewed)+'%':'—'} Icon={CheckCheck}/></div>
  <div className="dash-columns"><section className="panel"><h2>Highlight score distribution</h2><p className="muted">Generated clips by estimated highlight quality.</p>{m.score_distribution?.some(row=>row.count>0)?<div className="chart"><ResponsiveContainer width="100%" height={240}><BarChart data={m.score_distribution}><CartesianGrid stroke="#343541" vertical={false}/><XAxis dataKey="score" stroke="#aaa9b8"/><YAxis allowDecimals={false} stroke="#aaa9b8"/><Tooltip contentStyle={{background:'#20212c',border:'1px solid #454451'}}/><Bar dataKey="count" fill="#9c87ff" radius={[4,4,0,0]}/></BarChart></ResponsiveContainer></div>:<Empty title="No scored clips"/>}</section>
  <section className="panel"><h2>Processing time</h2><dl className="facts"><dt>Source duration processed</dt><dd>{time(m.source_seconds)}</dd><dt>Average processing time</dt><dd>{m.average_processing_seconds==null?'—':time(m.average_processing_seconds)}</dd>{Object.entries(m.stage_seconds||{}).map(([k,v])=><div className="fact-pair" key={k}><dt>{label(k)}</dt><dd>{time(v)}</dd></div>)}</dl></section></div><section className="panel"><h2>Rejected categories</h2>{Object.entries(m.rejected_categories||{}).length?<dl className="facts">{Object.entries(m.rejected_categories).map(([k,v])=><div className="fact-pair" key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>:<p className="muted">No clip rejections recorded.</p>}</section></>
}
