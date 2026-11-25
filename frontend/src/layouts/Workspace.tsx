import { useEffect, useState } from 'react'
import { Activity, AudioLines, ChevronRight, Clapperboard, Cpu, Film, FolderClosed, House, LayoutPanelLeft, ListVideo, Menu, PanelLeftClose, Plus, Settings2, SlidersHorizontal, Workflow, X } from 'lucide-react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'

const groups = [
  [{to:'/', text:'Dashboard', Icon:House}, {to:'/new', text:'New Project', Icon:Plus}, {to:'/projects', text:'My Projects', Icon:FolderClosed}, {to:'/clips', text:'Clip Library', Icon:ListVideo}, {to:'/editor',text:'Video Editor',Icon:SlidersHorizontal}],
  [{to:'/campaigns',text:'Campaigns',Icon:Clapperboard},{to:'/automation',text:'Automation',Icon:Workflow},{to:'/analytics',text:'Analytics',Icon:Activity},{to:'/settings',text:'Settings',Icon:Settings2}]
]
export function Brand(){return <span className="brand"><span className="brand-mark"><AudioLines size={22} strokeWidth={2.6}/></span><strong>MOMENTRIX</strong></span>}
export default function Workspace(){
  const [collapsed,setCollapsed]=useState(false)
  const [mobile,setMobile]=useState(false)
  const location=useLocation()
  useEffect(()=>setMobile(false),[location.pathname])
  const section=groups.flat().find(link => link.to==='/' ? location.pathname==='/' : location.pathname.startsWith(link.to))?.text || 'Workspace'
  return <div className={`studio ${collapsed?'collapsed':''} ${mobile?'nav-open':''}`}>
    <a className="skip" href="#main" onClick={e=>{e.preventDefault(); document.getElementById('main')?.focus()}}>Skip navigation</a>
    {mobile && <button className="backdrop" aria-label="Close navigation" onClick={()=>setMobile(false)}/>}
    <aside className="sidebar"><div className="brand-row"><Link to="/" aria-label="Momentrix dashboard"><Brand/></Link><button className="mobile-close" aria-label="Close menu" onClick={()=>setMobile(false)}><X size={19}/></button></div>
      <nav aria-label="Main navigation">{groups.map((group,i)=><div className="nav-group" key={i}>{group.map(({to,text,Icon})=><NavLink key={to} to={to} end={to==='/'} title={text}><Icon size={18} strokeWidth={1.7}/><span>{text}</span></NavLink>)}</div>)}</nav>
      <div className="sidebar-foot"><Cpu size={18}/><div><strong>Local workspace</strong><small>Private studio</small></div></div>
    </aside>
    <div className="workspace"><header className="topbar"><div className="top-left"><button className="desktop-toggle icon-plain" aria-label={collapsed?'Expand sidebar':'Collapse sidebar'} onClick={()=>setCollapsed(v=>!v)}>{collapsed?<LayoutPanelLeft size={18}/>:<PanelLeftClose size={18}/>}</button><button className="mobile-toggle icon-plain" aria-label="Open menu" onClick={()=>setMobile(true)}><Menu size={20}/></button><span className="path"><Film size={15}/>Studio<ChevronRight size={13}/><strong>{section}</strong></span></div><Link className="quick-create" to="/new"><Plus size={15}/>New project</Link></header>
      <main id="main" tabIndex={-1}><Outlet/></main>
    </div></div>
}
