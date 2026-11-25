import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../services/http'
export interface RenderTask {id:string;status:string;error?:string;clip_ids?:string[];kind?:string}
export function useRender(){
  const client=useQueryClient(),[task,setTask]=useState<RenderTask|null>(null),[error,setError]=useState(''),[submitting,setSubmitting]=useState(false)
  const poll=useQuery({queryKey:['/exports',task?.id],queryFn:()=>api<RenderTask>('/exports/'+task!.id),enabled:!!task,refetchInterval:q=>q.state.data && ['completed','cancelled','failed'].includes(q.state.data.status)?false:2000,retry:false})
  const result=poll.data||task
  useEffect(()=>{if(result?.status==='completed')void client.invalidateQueries({predicate:q=>typeof q.queryKey[0]==='string'&&(q.queryKey[0] as string).startsWith('/clips')})},[client,result?.status,result?.id])
  async function start(path:string,body?:unknown){setSubmitting(true);setError('');try{setTask(await api<RenderTask>(path,'POST',body))}catch(e){setError((e as Error).message)}finally{setSubmitting(false)}}
  return {start,result,busy:submitting||Boolean(result&&!['completed','failed','cancelled'].includes(result.status)),error:error||poll.error?.message||result?.error}
}
