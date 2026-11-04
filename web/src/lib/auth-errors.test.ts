import { describe, expect, it, vi } from 'vitest'
import type { SupabaseClient } from '@supabase/supabase-js'
import { checkAuth } from './auth-errors'

const storedUser = { id: 'user-1' }
const storedSession = { access_token: 't', user: storedUser }

function client(
  getUser: () => Promise<unknown>,
  getSession: () => Promise<unknown> = async () => ({ data: { session: storedSession }, error: null }),
): SupabaseClient {
  return { auth: { getUser: vi.fn(getUser), getSession: vi.fn(getSession) } } as unknown as SupabaseClient
}

describe('checkAuth', () => {
  it('returns the verified user with the session', async () => {
    const user = { id: 'user-2' }
    expect(await checkAuth(client(async () => ({ data: { user }, error: null })), vi.fn())).toEqual({
      kind: 'signed_in', user, session: storedSession,
    })
  })

  it('signs out only when the server rejects the token', async () => {
    const rejected = client(async () => ({ data: { user: null }, error: { status: 403 } }))
    expect(await checkAuth(rejected, vi.fn())).toEqual({ kind: 'signed_out' })
  })

  it('treats a missing session as signed out without calling the server', async () => {
    const getUser = vi.fn()
    const anonymous = client(getUser, async () => ({ data: { session: null }, error: null }))
    expect(await checkAuth(anonymous, vi.fn())).toEqual({ kind: 'signed_out' })
    expect(getUser).not.toHaveBeenCalled()
  })

  it('keeps the stored session when verification fails transiently', async () => {
    const outage = client(async () => ({ data: { user: null }, error: { status: 502 } }))
    expect(await checkAuth(outage, vi.fn())).toMatchObject({ kind: 'signed_in', user: storedUser })
    const offline = client(async () => { throw new Error('Failed to fetch') })
    expect(await checkAuth(offline, vi.fn())).toMatchObject({ kind: 'signed_in', user: storedUser })
  })

  it('reports unavailable when the session refresh fails transiently', async () => {
    const refreshDown = client(vi.fn(), async () => ({ data: { session: null }, error: { status: 0 } }))
    expect(await checkAuth(refreshDown, vi.fn())).toEqual({ kind: 'unavailable' })
  })

  it('reports unavailable when reading the session hangs past the timeout', async () => {
    vi.useFakeTimers()
    const hung = client(vi.fn(), () => new Promise(() => {}))
    const result = checkAuth(hung, vi.fn())
    await vi.advanceTimersByTimeAsync(10_001)
    expect(await result).toEqual({ kind: 'unavailable' })
    vi.useRealTimers()
  })

  it('admits a slow verification but bounces once the server rejects it', async () => {
    vi.useFakeTimers()
    let respond!: (value: unknown) => void
    const slow = client(() => new Promise((resolve) => { respond = resolve }))
    const onLateRejection = vi.fn()
    const result = checkAuth(slow, onLateRejection)
    await vi.advanceTimersByTimeAsync(10_001)
    expect(await result).toMatchObject({ kind: 'signed_in', user: storedUser })
    expect(onLateRejection).not.toHaveBeenCalled()

    respond({ data: { user: null }, error: { status: 403 } })
    await vi.runAllTimersAsync()
    expect(onLateRejection).toHaveBeenCalledOnce()
    vi.useRealTimers()
  })
})
