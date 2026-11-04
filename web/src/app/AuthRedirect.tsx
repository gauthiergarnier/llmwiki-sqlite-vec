'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

export function AuthRedirect() {
  const router = useRouter()

  useEffect(() => {
    if (isLocal) {
      router.replace('/wikis')
      return
    }

    import('@/lib/supabase/client').then(({ createClient }) => {
      const supabase = createClient()
      supabase.auth.getUser().then(({ data: { user } }) => {
        if (user) router.replace('/wikis')
      })
    })
  }, [router])

  return null
}
