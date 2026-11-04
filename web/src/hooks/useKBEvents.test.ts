import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import type { KnowledgeBaseEvent } from '@/lib/types'
import { useKBEvents } from './useKBEvents'

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }))

const apiFetchMock = vi.mocked(apiFetch)

function event(id: string): KnowledgeBaseEvent {
  return { id } as KnowledgeBaseEvent
}

beforeEach(() => {
  apiFetchMock.mockReset()
  useUserStore.setState({ accessToken: 'token-1' })
})

afterEach(() => {
  cleanup()
})

describe('useKBEvents', () => {
  it('keeps loaded events when the access token rotates', async () => {
    apiFetchMock.mockResolvedValue({ items: [event('e1')], next_cursor: null })
    const { result } = renderHook(() => useKBEvents('kb-1', true, 'v1'))
    await waitFor(() => expect(result.current.events).toHaveLength(1))

    act(() => {
      useUserStore.setState({ accessToken: 'token-2' })
    })

    expect(result.current.loading).toBe(false)
    expect(result.current.events).toHaveLength(1)
    expect(apiFetchMock).toHaveBeenCalledTimes(1)
  })
})
