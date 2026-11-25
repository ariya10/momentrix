import { lazy, Suspense, useEffect, useState, type FormEvent } from 'react'
import { ArrowRight, KeyRound } from 'lucide-react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import Workspace, { Brand } from './layouts/Workspace'
import { Alert, Field, Loading, useApi } from './components/common'
import { Button } from './components/ui/button'
import { api } from './services/http'
import { Dashboard, Projects, ProjectPage, Automation, Settings } from './pages/WorkspacePages'
import NewProject from './pages/NewProject'
import { Campaigns } from './pages/Campaigns'
import { ClipLibrary } from './pages/Clips'
const Editor = lazy(() => import('./editor/Editor'))
const Analytics = lazy(() => import('./pages/Analytics'))

export default function App(){
  const client=useQueryClient()
  const session=useApi<{authenticated:boolean}>('/session')
  const [token,setToken]=useState('')
  const login=useMutation({mutationFn:()=>api('/session','POST',{token}),onSuccess:()=>{setToken(''); void client.invalidateQueries({queryKey:['/session']})}})
  useEffect(()=>{const expired=()=>{client.clear(); void client.invalidateQueries()};window.addEventListener('studio-session-expired',expired);return ()=>window.removeEventListener('studio-session-expired',expired)},[client])
  function submit(e:FormEvent){e.preventDefault();login.mutate()}
  if(session.isPending)return <Loading message="Opening local studio…"/>
  if(!session.data?.authenticated)return <div className="login"><div className="login-box"><Brand/><span className="login-icon"><KeyRound size={23}/></span><h1>Open your studio</h1><p>Run <code>.\scripts\show_studio_key.ps1</code> in PowerShell and enter the studio key below.</p><form onSubmit={submit}><Field name="Studio access key"><input type="password" autoComplete="current-password" value={token} onChange={e=>setToken(e.target.value)}/></Field><Alert error={session.error || login.error}/><Button type="submit" disabled={login.isPending}>Open workspace <ArrowRight size={17}/></Button></form></div></div>
  return <Suspense fallback={<Loading/>}><Routes><Route element={<Workspace/>}><Route index element={<Dashboard/>}/><Route path="new" element={<NewProject/>}/><Route path="projects" element={<Projects/>}/><Route path="projects/:id" element={<ProjectPage/>}/><Route path="clips" element={<ClipLibrary/>}/><Route path="editor" element={<ClipLibrary selectForEdit/>}/><Route path="editor/:id" element={<Editor/>}/><Route path="campaigns" element={<Campaigns/>}/><Route path="automation" element={<Automation/>}/><Route path="analytics" element={<Analytics/>}/><Route path="settings" element={<Settings/>}/><Route path="*" element={<Navigate to="/" replace/>}/></Route></Routes></Suspense>
}
