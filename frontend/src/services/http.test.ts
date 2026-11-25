import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, date, time } from './http'

describe('HTTP service', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reads structured FastAPI errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: [{ loc: ['body', 'name'], msg: 'required' }] }),
    }))

    await expect(api('/campaigns', 'POST', {})).rejects.toThrow('name – required')
  })

  it('handles session expiry separately', async () => {
    const dispatch = vi.spyOn(window, 'dispatchEvent')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'Session expired' }),
    }))

    await expect(api('/projects')).rejects.toThrow('Session expired')
    expect(dispatch).toHaveBeenCalled()
  })
})

describe('display formatting', () => {
  it('formats elapsed time and invalid timestamps safely', () => {
    expect(time(65)).toBe('1:05')
    expect(time(Number.NaN)).toBe('—')
    expect(date(null)).toBe('—')
  })
})
