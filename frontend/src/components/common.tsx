import type { ReactNode } from 'react'
import { AlertCircle, CheckCircle2, CircleDashed, LoaderCircle, ScanLine } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { api, label } from '../services/http'

export function useApi<T>(path: string, interval?: number) {
  return useQuery<T, Error>({ queryKey: [path], queryFn: () => api<T>(path), refetchInterval: interval, retry: false })
}
export function Alert({ error }: { error?: Error | string | null }) {
  return error ? <div className="alert" role="alert"><AlertCircle size={17}/><span>{typeof error === 'string' ? error : error.message}</span></div> : null
}
export function Loading({ message = 'Loading workspace…' }: { message?: string }) {
  return <div className="loading" role="status"><LoaderCircle className="spin" size={18}/>{message}</div>
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><ScanLine strokeWidth={1.2} size={34}/><h3>{title}</h3>{children && <p>{children}</p>}</div>
}
export function Badge({ value }: { value: string }) {
  const color = ['approved','completed','exported','connected'].includes(value) ? 'green' : ['failed','rejected','disconnected'].includes(value) ? 'red' : ['awaiting_review','completed_with_warnings','pending'].includes(value) ? 'amber' : 'violet'
  return <span className={`badge ${color}`}><i/>{label(value)}</span>
}
export function PageHead({ title, sub, action }: { title: string; sub?: string; action?: ReactNode }) {
  return <header className="page-head"><div><h1>{title}</h1>{sub && <p>{sub}</p>}</div>{action}</header>
}
export function Field({ name, children }: { name: string; children: ReactNode }) {
  return <label className="field"><span>{name}</span>{children}</label>
}
export function Check({ good, name }: { good: boolean; name: string }) {
  return <div className="health-line">{good ? <CheckCircle2 size={16} className="mint"/> : <CircleDashed size={16} className="amber-text"/>}{name}<span>{good ? 'Ready' : 'Unavailable'}</span></div>
}
