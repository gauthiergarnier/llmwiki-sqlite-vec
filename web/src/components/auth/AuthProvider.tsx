'use client'

import * as React from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { useUserStore, useKBStore } from '@/stores'
import { apiFetch, isApiError } from '@/lib/api'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

function isAuthFailure(err: unknown): boolean {
  return isApiError(err) && (err.status === 401 || err.status === 403)
}

interface AuthProviderProps {
  userId: string
  email: string
  /** Token from the session the dashboard layout already verified; later rotations arrive via onAuthStateChange. */
  accessToken: string
  children: React.ReactNode
}

export function AuthProvider({ userId, email, accessToken, children }: AuthProviderProps) {
  const router = useRouter()
  const pathname = usePathname()
  const setUser = useUserStore((s) => s.setUser)
  const setAccessToken = useUserStore((s) => s.setAccessToken)
  const setOnboarded = useUserStore((s) => s.setOnboarded)
  const signOut = useUserStore((s) => s.signOut)
  const onboarded = useUserStore((s) => s.onboarded)
  const fetchKBs = useKBStore((s) => s.fetchKBs)
  const pathnameRef = React.useRef(pathname)

  React.useEffect(() => {
    pathnameRef.current = pathname
  }, [pathname])

  React.useEffect(() => {
    if (isLocal) {
      setUser({ id: userId, email })
      setAccessToken(accessToken)
      setOnboarded(true)
      fetchKBs()
      return
    }

    let cancelled = false
    let subscription: { unsubscribe: () => void } | undefined

    import('@/lib/supabase/client').then(({ createClient }) => {
      if (cancelled) return
      const supabase = createClient()

      const bounceToLogin = async () => {
        try { await supabase.auth.signOut({ scope: 'local' }) } catch { /* best-effort */ }
        signOut()
        useKBStore.setState({ knowledgeBases: [], loading: false, error: null })
        if (!cancelled) router.replace('/login')
      }

      ;(async () => {
        try {
          setUser({ id: userId, email })
          setAccessToken(accessToken)
          try {
            await fetchKBs({ throwOnError: true })
          } catch (err) {
            if (isAuthFailure(err)) {
              await bounceToLogin()
              return
            }
          }

          try {
            const me = await apiFetch<{ onboarded: boolean }>('/v1/me', accessToken)
            if (cancelled) return
            setOnboarded(me.onboarded)
            if (!me.onboarded && pathnameRef.current !== '/onboarding') {
              router.replace('/onboarding')
            }
          } catch {
            const stored = useUserStore.getState().onboarded
            if (stored === null) setOnboarded(true)
          }
        } catch {
          await bounceToLogin()
        }
      })()

      // Only an explicit SIGNED_OUT logs out; a null INITIAL_SESSION can be a transient storage/refresh failure.
      const { data } = supabase.auth.onAuthStateChange((event, session) => {
        if (cancelled) return
        if (session) {
          useUserStore.getState().setAccessToken(session.access_token)
        } else if (event === 'SIGNED_OUT') {
          signOut()
          useKBStore.setState({ knowledgeBases: [], loading: false, error: null })
          router.replace('/login')
        }
      })
      subscription = data.subscription
    })

    return () => {
      cancelled = true
      subscription?.unsubscribe()
    }
  }, [userId, email, accessToken, setUser, setAccessToken, setOnboarded, fetchKBs, router, signOut])

  React.useEffect(() => {
    if (!isLocal && onboarded === false && pathname !== '/onboarding') {
      router.replace('/onboarding')
    }
  }, [onboarded, pathname, router])

  return <>{children}</>
}
