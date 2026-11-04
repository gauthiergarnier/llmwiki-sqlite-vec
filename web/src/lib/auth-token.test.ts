import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createClient } from '@/lib/supabase/client'
import { useUserStore } from '@/stores/useUserStore'
import { refreshAccessToken } from './auth-token'

vi.mock('@/lib/supabase/client', () => ({ createClient: vi.fn() }))

const createClientMock = vi.mocked(createClient)

beforeEach(() => {
  createClientMock.mockReset()
  useUserStore.setState({ accessToken: 'old-token' })
})

describe('refreshAccessToken', () => {
  it('coalesces simultaneous refreshes and updates the store once', async () => {
    let resolveRefresh!: (value: {
      data: { session: { access_token: string } }
      error: null
    }) => void
    const refresh = new Promise<{
      data: { session: { access_token: string } }
      error: null
    }>((resolve) => {
      resolveRefresh = resolve
    })
    const refreshSession = vi.fn().mockReturnValue(refresh)
    createClientMock.mockReturnValue({
      auth: { refreshSession, getSession: vi.fn() },
    } as unknown as ReturnType<typeof createClient>)

    const first = refreshAccessToken('old-token')
    const second = refreshAccessToken('old-token')
    resolveRefresh({ data: { session: { access_token: 'new-token' } }, error: null })

    await expect(Promise.all([first, second])).resolves.toEqual(['new-token', 'new-token'])
    expect(refreshSession).toHaveBeenCalledOnce()
    expect(useUserStore.getState().accessToken).toBe('new-token')
  })

  it('returns a token that Supabase already refreshed without another exchange', async () => {
    useUserStore.setState({ accessToken: 'new-token' })

    await expect(refreshAccessToken('old-token')).resolves.toBe('new-token')
    expect(createClientMock).not.toHaveBeenCalled()
  })

  it('does not reuse the token that the API rejected when refresh fails', async () => {
    const refreshSession = vi.fn().mockResolvedValue({
      data: { session: null },
      error: new Error('refresh failed'),
    })
    const getSession = vi.fn().mockResolvedValue({
      data: { session: { access_token: 'old-token' } },
      error: null,
    })
    createClientMock.mockReturnValue({
      auth: { refreshSession, getSession },
    } as unknown as ReturnType<typeof createClient>)

    await expect(refreshAccessToken('old-token')).resolves.toBeNull()
    expect(getSession).toHaveBeenCalledOnce()
    expect(useUserStore.getState().accessToken).toBe('old-token')
  })
})
