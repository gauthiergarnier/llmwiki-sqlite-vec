import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from './AuthProvider'

type Listener = (event: string, session: { access_token: string } | null) => void

const replace = vi.fn()
let listener: Listener | null = null

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace }),
  usePathname: () => '/wikis',
}))

vi.mock('@/lib/supabase/client', () => ({
  createClient: () => ({
    auth: {
      signOut: vi.fn(async () => ({ error: null })),
      onAuthStateChange: (cb: Listener) => {
        listener = cb
        return { data: { subscription: { unsubscribe: vi.fn() } } }
      },
    },
  }),
}))

vi.mock('@/lib/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/api')>()
  return { ...original, apiFetch: vi.fn(async (path: string) => (path === '/v1/me' ? { onboarded: true } : [])) }
})

afterEach(() => {
  cleanup()
  replace.mockReset()
  listener = null
})

describe('AuthProvider', () => {
  it('keeps the user signed in on a transient null session and logs out only on SIGNED_OUT', async () => {
    render(<AuthProvider userId="u1" email="u@example.com" accessToken="token-1"><div /></AuthProvider>)
    await waitFor(() => expect(listener).not.toBeNull())

    act(() => listener!('INITIAL_SESSION', null))
    expect(replace).not.toHaveBeenCalledWith('/login')

    act(() => listener!('SIGNED_OUT', null))
    expect(replace).toHaveBeenCalledWith('/login')
  })
})
