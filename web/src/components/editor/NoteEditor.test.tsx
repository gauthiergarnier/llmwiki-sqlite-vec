import { act, cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiFetch } from '@/lib/api'
import { NoteEditor } from './NoteEditor'

vi.mock('@/stores', () => ({
  useUserStore: { getState: () => ({ accessToken: 'test-token' }) },
}))

vi.mock('@/lib/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/api')>()
  return { ...original, apiFetch: vi.fn() }
})

const apiFetchMock = vi.mocked(apiFetch)

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  apiFetchMock.mockReset()
})

describe('NoteEditor', () => {
  it('does not save a note just because it was opened', async () => {
    vi.useFakeTimers()
    apiFetchMock.mockResolvedValue({ id: 'doc-1', content: '# Title\n\n<div>raw html</div>\n\nBody[^1]\n\n[^1]: note', version: 3 })

    render(<NoteEditor documentId="doc-1" embedded hideToolbar />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })

    const writes = apiFetchMock.mock.calls.filter(([, , init]) => init?.method && init.method !== 'GET')
    expect(apiFetchMock).toHaveBeenCalledWith('/v1/documents/doc-1/content', 'test-token')
    expect(writes).toEqual([])
  })
})
