'use client'

import { CircleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function AuthUnavailable() {
  return (
    <div role="alert" className="flex min-h-svh flex-col items-center justify-center gap-3 bg-background p-8 text-center">
      <CircleAlert className="size-5 text-muted-foreground" />
      <div>
        <p className="text-sm font-medium">Can&apos;t reach the sign-in service</p>
        <p className="mt-1 text-xs text-muted-foreground">You&apos;re still signed in. Check your connection and try again.</p>
      </div>
      <Button variant="outline" size="sm" onClick={() => window.location.reload()}>Retry</Button>
    </div>
  )
}
