'use client'

import { CircleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function DocumentsLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="flex h-full flex-col items-center justify-center gap-3 text-center">
      <CircleAlert className="size-5 text-muted-foreground" />
      <div>
        <p className="text-sm font-medium">Couldn&apos;t load this wiki</p>
        <p className="mt-1 text-xs text-muted-foreground">Your pages are safe — this is a connection problem.</p>
      </div>
      <Button variant="outline" size="sm" onClick={onRetry}>Retry</Button>
    </div>
  )
}
