export const apiBase = '/api/v2'
export const clientHeader = { 'X-Momentrix-Client': 'website' }

function errorDetail(status: number, payload: unknown): string {
  const detail = (payload as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((issue) => [issue.loc?.slice(1)?.join('.'), issue.msg].filter(Boolean).join(' – ')).join('\n')
  return `Request failed (HTTP ${status}).`
}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(apiBase + path, {
    method, credentials: 'same-origin', cache: 'no-store',
    headers: { ...(method !== 'GET' && clientHeader), ...(body !== undefined && { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    if (response.status === 401 && path !== '/session') window.dispatchEvent(new Event('studio-session-expired'))
    throw new Error(errorDetail(response.status, await response.json().catch(() => null)))
  }
  return response.status === 204 ? undefined as T : response.json()
}

export function uploadFile<T>(path: string, file: File, progress: (sent: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const transfer = new XMLHttpRequest()
    transfer.open('POST', apiBase + path)
    transfer.setRequestHeader('Content-Type', 'application/octet-stream')
    transfer.setRequestHeader('X-Filename', encodeURIComponent(file.name))
    transfer.setRequestHeader('X-Momentrix-Client', 'website')
    transfer.upload.onprogress = (event) => { if (event.lengthComputable) progress(event.loaded / event.total) }
    transfer.onerror = () => reject(new Error('The upload connection closed. Check the backend and retry.'))
    transfer.onload = () => {
      let data: unknown
      try { data = JSON.parse(transfer.responseText) } catch { data = null }
      if (transfer.status < 200 || transfer.status >= 300) reject(new Error(errorDetail(transfer.status, data)))
      else resolve(data as T)
    }
    transfer.send(file)
  })
}

export function time(seconds: number, precise = false): string {
  if (!Number.isFinite(seconds)) return '—'
  const min = Math.floor(seconds / 60)
  const sec = Math.floor(seconds % 60)
  return `${min}:${String(sec).padStart(2, '0')}${precise ? '.' + String(Math.floor((seconds % 1) * 10)) : ''}`
}
export function date(value?: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
export function label(value: string) { return value.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase()) }
