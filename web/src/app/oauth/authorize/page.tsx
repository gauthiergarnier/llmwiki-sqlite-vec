'use client'

import * as React from 'react'
import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import { Loader2, Shield, Check, X } from 'lucide-react'
import type { OAuthAuthorizationDetails } from '@supabase/supabase-js'
import { createClient } from '@/lib/supabase/client'
import { Button } from '@/components/ui/button'

function redirectHost(uri: string): string {
  try {
    return new URL(uri).host
  } catch {
    return uri
  }
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message
  return fallback
}

function OAuthConsentContent() {
  const searchParams = useSearchParams()
  const authorizationId = searchParams.get('authorization_id')

  const [details, setDetails] = React.useState<OAuthAuthorizationDetails | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [submitting, setSubmitting] = React.useState(false)
  const [success, setSuccess] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!authorizationId) {
      setError('Missing authorization_id')
      setLoading(false)
      return
    }

    const supabase = createClient()

    supabase.auth.getUser().then(async ({ data: { user } }) => {
      if (!user) {
        const returnUrl = `/oauth/authorize?authorization_id=${authorizationId}`
        window.location.href = `/login?returnTo=${encodeURIComponent(returnUrl)}`
        return
      }

      try {
        const { data, error: fetchError } = await supabase.auth.oauth.getAuthorizationDetails(authorizationId)
        if (fetchError) throw fetchError
        if ('redirect_url' in data) {
          window.location.href = data.redirect_url
          return
        }
        setDetails(data)
      } catch (err: unknown) {
        console.error('Failed to get authorization details:', err)
        setError(errorMessage(err, 'Could not load this authorization request. Start the connection again from your AI client.'))
      } finally {
        setLoading(false)
      }
    })
  }, [authorizationId])

  const handleDecision = async (approve: boolean) => {
    if (!authorizationId || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const oauth = createClient().auth.oauth
      const { data, error: decisionError } = approve
        ? await oauth.approveAuthorization(authorizationId)
        : await oauth.denyAuthorization(authorizationId)
      if (decisionError) throw decisionError
      if (data?.redirect_url) {
        window.location.href = data.redirect_url
      } else {
        setSuccess(approve ? 'Access granted successfully.' : 'Access denied.')
      }
    } catch (err: unknown) {
      setError(errorMessage(err, approve ? 'Failed to approve authorization.' : 'Failed to deny authorization.'))
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-svh flex items-center justify-center bg-background">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (success) {
    return (
      <div className="min-h-svh flex items-center justify-center bg-background p-8">
        <div className="text-center max-w-sm">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-green-100 dark:bg-green-500/10 mb-4">
            <Check className="size-5 text-green-600 dark:text-green-400" />
          </div>
          <h1 className="text-lg font-semibold mb-2">{success}</h1>
          <p className="text-sm text-muted-foreground">You can close this window.</p>
        </div>
      </div>
    )
  }

  if (error && !details) {
    return (
      <div className="min-h-svh flex items-center justify-center bg-background p-8">
        <div className="text-center max-w-sm">
          <X className="size-10 text-destructive mx-auto mb-4" />
          <h1 className="text-lg font-semibold mb-2">Authorization Error</h1>
          <p className="text-sm text-muted-foreground">{error}</p>
        </div>
      </div>
    )
  }

  if (!details) return null

  const clientName = details.client.name || 'An MCP client'
  const returnHost = redirectHost(details.redirect_uri)

  return (
    <div className="min-h-svh flex items-center justify-center bg-background p-8">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-muted mb-4">
            <Shield className="size-5 text-foreground" />
          </div>
          <h1 className="text-xl font-semibold tracking-tight">Connect {clientName}</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{clientName}</span> wants to connect
            to your LLM Wiki as an MCP server.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            After approving you&apos;ll be sent to <span className="font-medium text-foreground">{returnHost}</span>
          </p>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 mb-4">
            <p className="text-sm text-destructive">{error}</p>
          </div>
        )}

        <div className="rounded-lg border border-border p-4 mb-6">
          <p className="text-sm font-medium mb-2">{clientName} will be able to:</p>
          <ul className="space-y-1.5 text-sm text-muted-foreground">
            <li className="flex items-start gap-2">
              <span className="text-green-500 mt-0.5">&#10003;</span>
              Read your uploaded documents and sources
            </li>
            <li className="flex items-start gap-2">
              <span className="text-green-500 mt-0.5">&#10003;</span>
              Search across your knowledge bases
            </li>
            <li className="flex items-start gap-2">
              <span className="text-green-500 mt-0.5">&#10003;</span>
              Create, edit, and maintain wiki pages
            </li>
            <li className="flex items-start gap-2">
              <span className="text-green-500 mt-0.5">&#10003;</span>
              Delete documents and wiki pages
            </li>
          </ul>
        </div>

        <div className="flex gap-3">
          <Button
            variant="outline"
            onClick={() => handleDecision(false)}
            disabled={submitting}
            className="flex-1"
          >
            Deny
          </Button>
          <Button
            onClick={() => handleDecision(true)}
            disabled={submitting}
            className="flex-1"
          >
            {submitting && <Loader2 size={14} className="animate-spin" />}
            Approve
          </Button>
        </div>

        <p className="mt-4 text-[11px] text-center text-muted-foreground/50">
          You can revoke access at any time from Settings.
        </p>
      </div>
    </div>
  )
}

export default function OAuthConsentPage() {
  return (
    <Suspense>
      <OAuthConsentContent />
    </Suspense>
  )
}
