import { beforeEach, describe, expect, it, vi } from 'vitest'
import { refreshAccessToken } from './auth-token'
import { ApiError, apiFetch } from './api'
import { useUserStore } from '@/stores/useUserStore'

vi.mock('./auth-token', () => ({ refreshAccessToken: vi.fn() }))

const fetchMock = vi.fn<typeof fetch>()
const refreshAccessTokenMock = vi.mocked(refreshAccessToken)

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  fetchMock.mockReset()
  refreshAccessTokenMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  useUserStore.setState({ accessToken: 'old-token' })
})

describe('apiFetch authentication', () => {
  it('retries a 401 once with a refreshed access token', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: 'Invalid token' }, 401))
      .mockResolvedValueOnce(jsonResponse({ ok: true }))
    refreshAccessTokenMock.mockResolvedValueOnce('new-token')

    await expect(apiFetch<{ ok: boolean }>('/v1/test', 'old-token', {
      method: 'POST',
      body: JSON.stringify({ value: 1 }),
    })).resolves.toEqual({ ok: true })

    expect(refreshAccessTokenMock).toHaveBeenCalledOnce()
    expect(refreshAccessTokenMock).toHaveBeenCalledWith('old-token')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('Authorization')).toBe('Bearer old-token')
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get('Authorization')).toBe('Bearer new-token')
    expect(fetchMock.mock.calls[1][1]?.body).toBe(JSON.stringify({ value: 1 }))
  })

  it('uses a newer store token before making the first request', async () => {
    useUserStore.setState({ accessToken: 'newer-token' })
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: true }))

    await apiFetch('/v1/test', 'captured-token')

    expect(fetchMock).toHaveBeenCalledOnce()
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('Authorization')).toBe('Bearer newer-token')
    expect(refreshAccessTokenMock).not.toHaveBeenCalled()
  })

  it('does not refresh for an authorization failure', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Forbidden' }, 403))

    await expect(apiFetch('/v1/test', 'old-token')).rejects.toMatchObject({
      status: 403,
      message: 'Forbidden',
    })
    expect(refreshAccessTokenMock).not.toHaveBeenCalled()
  })

  it('preserves the original 401 when no fresh token is available', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Invalid token' }, 401))
    refreshAccessTokenMock.mockResolvedValueOnce(null)

    const error = await apiFetch('/v1/test', 'old-token').catch((err: unknown) => err)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 401, message: 'Invalid token' })
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('preserves the original 401 when the refresh request fails', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Invalid token' }, 401))
    refreshAccessTokenMock.mockRejectedValueOnce(new Error('auth service unavailable'))

    await expect(apiFetch('/v1/test', 'old-token')).rejects.toMatchObject({
      status: 401,
      message: 'Invalid token',
    })
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('does not loop when the refreshed token is also rejected', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: 'Invalid token' }, 401))
      .mockResolvedValueOnce(jsonResponse({ detail: 'Invalid token' }, 401))
    refreshAccessTokenMock.mockResolvedValueOnce('new-token')

    await expect(apiFetch('/v1/test', 'old-token')).rejects.toMatchObject({ status: 401 })
    expect(refreshAccessTokenMock).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
