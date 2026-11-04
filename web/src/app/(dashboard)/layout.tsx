'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { AppShell } from '@/components/layout/AppShell'
import { AuthProvider } from '@/components/auth/AuthProvider'
import { checkAuth } from '@/lib/auth-errors'
import { AuthUnavailable } from '@/components/auth/AuthUnavailable'
import { ONBOARDING_PREVIEW_ENABLED } from '@/lib/onboarding-preview'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  if (ONBOARDING_PREVIEW_ENABLED && pathname === '/onboarding') {
    return <AppShell>{children}</AppShell>
  }

  if (isLocal) {
    return (
      <AuthProvider userId="local" email="local@localhost" accessToken="local">
        <AppShell>{children}</AppShell>
      </AuthProvider>
    )
  }

  return <HostedDashboard>{children}</HostedDashboard>
}

function HostedDashboard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [user, setUser] = useState<{ id: string; email: string; accessToken: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [authUnavailable, setAuthUnavailable] = useState(false)
  const pathnameRef = useRef(pathname)

  useEffect(() => {
    pathnameRef.current = pathname
  }, [pathname])

  useEffect(() => {
    let cancelled = false

    const bounceToLogin = async () => {
      try {
        const { createClient } = await import('@/lib/supabase/client')
        await createClient().auth.signOut({ scope: 'local' })
      } catch { /* signOut best-effort */ }
      const currentPath = pathnameRef.current
      const returnTo = currentPath !== '/wikis' ? `?returnTo=${encodeURIComponent(currentPath)}` : ''
      if (!cancelled) router.replace(`/login${returnTo}`)
    }

    import('@/lib/supabase/client').then(async ({ createClient }) => {
      if (cancelled) return
      const supabase = createClient()
      const auth = await checkAuth(supabase, bounceToLogin)
      if (cancelled) return
      if (auth.kind === 'signed_out') {
        await bounceToLogin()
        return
      }
      if (auth.kind === 'unavailable') {
        setAuthUnavailable(true)
        return
      }
      setUser({ id: auth.user.id, email: auth.user.email!, accessToken: auth.session.access_token })
      setLoading(false)
    }).catch(() => {
      if (!cancelled) setAuthUnavailable(true)
    })

    return () => { cancelled = true }
  }, [router])

  if (authUnavailable) return <AuthUnavailable />
  if (loading) return null

  return (
    <AuthProvider userId={user!.id} email={user!.email} accessToken={user!.accessToken}>
      <AppShell>{children}</AppShell>
    </AuthProvider>
  )
}
