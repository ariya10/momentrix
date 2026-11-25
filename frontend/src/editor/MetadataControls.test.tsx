import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../services/http'
import type { PublishingMetadata } from '../types'
import MetadataControls from './MetadataControls'

vi.mock('../services/http', () => ({api: vi.fn()}))
const original: PublishingMetadata = {
  title: 'Original title', hook: 'Original hook', caption: 'A bridge', description: 'A bridge made of paper',
  hashtags: ['#Bridge'], instagram_caption: '', tiktok_caption: '', thumbnail_text: '',
}

function controls(onChange: (value: PublishingMetadata) => void, hasUnsavedEdit = false) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}})
  render(<QueryClientProvider client={client}>
    <MetadataControls clipId="sample:clip_01" revision={2} value={original}
      onChange={onChange} hasUnsavedEdit={hasUnsavedEdit}/>
  </QueryClientProvider>)
  fireEvent.click(screen.getByText('Publishing metadata',{exact:true}))
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('Publishing metadata', () => {
  it('presents the grounded suggestion before applying it to the draft', async () => {
    const revised = {...original, title:'The bridge held'}
    vi.mocked(api).mockResolvedValue({
      status:'completed',
      suggestion:{metadata:revised, alternative_hooks:['Does it hold?'], evidence_quote:'The paper bridge held',
        evidence_event:null, editing_notes:'Keep the ending.'},
    })
    const onChange = vi.fn()
    controls(onChange)
    expect(await screen.findByText('The paper bridge held')).toBeVisible()
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button',{name:'Use suggestion'}))
    expect(onChange).toHaveBeenCalledWith(revised)
  })

  it('blocks fresh suggestions while timeline edits are unsaved', () => {
    vi.mocked(api).mockResolvedValue(null)
    controls(vi.fn(),true)
    expect(screen.getByRole('button',{name:'Regenerate metadata'})).toBeDisabled()
  })
})
