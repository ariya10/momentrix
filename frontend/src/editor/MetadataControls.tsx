import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { Alert, Field } from '../components/common'
import { Button } from '../components/ui/button'
import { api } from '../services/http'
import type { PublishingMetadata } from '../types'

interface Suggestion {
  metadata: PublishingMetadata
  alternative_hooks: string[]
  evidence_quote: string
  evidence_event: number | null
  editing_notes: string
}

interface MetadataTask {
  status: string
  error?: string
  suggestion?: Suggestion
}

interface Props {
  clipId: string
  revision: number
  value: PublishingMetadata
  onChange: (value: PublishingMetadata) => void
  hasUnsavedEdit: boolean
}

const active = (task?: MetadataTask | null) => task?.status === 'queued' || task?.status === 'working'

export default function MetadataControls({clipId, revision, value, onChange, hasUnsavedEdit}: Props) {
  const path = '/clips/' + clipId + '/metadata/suggestion'
  const queryKey = [path, revision]
  const client = useQueryClient()
  const latest = useQuery({
    queryKey,
    queryFn: () => api<MetadataTask | null>(path),
    refetchInterval: query => active(query.state.data) ? 2000 : false,
  })
  const generate = useMutation({
    mutationFn: () => api<MetadataTask>(path, 'POST', {revision}),
    onSuccess: task => client.setQueryData(queryKey, task),
  })
  const update = <K extends keyof PublishingMetadata>(key: K, field: PublishingMetadata[K]) =>
    onChange({...value, [key]: field})
  const suggestion = latest.data?.status === 'completed' ? latest.data.suggestion : undefined
  const editing = active(latest.data) || generate.isPending
  const textFields = {
    caption: 'General caption',
    description: 'Description',
    instagram_caption: 'Instagram Reels caption',
    tiktok_caption: 'TikTok caption',
  } as const

  return <details>
    <summary>Publishing metadata</summary>
    <Button variant="secondary" size="small" disabled={hasUnsavedEdit || editing}
      onClick={() => generate.mutate()}><Sparkles size={15}/>Regenerate metadata</Button>
    {hasUnsavedEdit && <p className="small muted">Save timeline edits before asking for a new suggestion.</p>}
    {editing && <p role="status">Generating a local suggestion…</p>}
    <Alert error={generate.error || latest.error || latest.data?.error}/>
    {suggestion && <div className="rule-box">
      <strong>Suggested title</strong>
      <p>{suggestion.metadata.title}</p>
      {suggestion.evidence_quote
        ? <blockquote>{suggestion.evidence_quote}</blockquote>
        : <p>Based on a measured event in the saved selection.</p>}
      <p>{suggestion.editing_notes}</p>
      <Button variant="secondary" size="small" onClick={() => onChange(suggestion.metadata)}>Use suggestion</Button>
      <Field name="Alternative publishing hook"><select value="" onChange={e => update('hook', e.target.value)}>
        <option value="">Choose an alternative</option>
        {Array.from(new Set(suggestion.alternative_hooks)).map(hook => <option key={hook}>{hook}</option>)}
      </select></Field>
    </div>}
    <Field name="YouTube Shorts title"><input value={value.title} maxLength={100}
      onChange={e => update('title', e.target.value)}/></Field>
    <Field name="Publishing hook"><input value={value.hook} maxLength={120}
      onChange={e => update('hook', e.target.value)}/></Field>
    {(Object.keys(textFields) as (keyof typeof textFields)[]).map(key =>
      <Field key={key} name={textFields[key]}><textarea rows={3} value={value[key]}
        maxLength={key === 'description' ? 800 : 600} onChange={e => update(key, e.target.value)}/></Field>
    )}
    <Field name="Thumbnail text"><input value={value.thumbnail_text} maxLength={80}
      onChange={e => update('thumbnail_text', e.target.value)}/></Field>
    <Field name="Hashtags"><input value={value.hashtags.join(' ')}
      onChange={e => update('hashtags', e.target.value.split(' '))}/></Field>
  </details>
}
