'use client'

import * as React from 'react'
import { Copy, Check, ArrowLeft } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { cn } from '@/lib/utils'
import { apiFetch } from '@/lib/api'
import { buildOAuthMcpConfig, MCP_URL } from '@/lib/mcp'
import { useUserStore } from '@/stores'

interface Usage {
  total_pages: number
  total_storage_bytes: number
  document_count: number
  max_pages: number
  max_storage_bytes: number
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / Math.pow(1024, i)
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[i]}`
}

interface IndexStats {
  documents: { total: number; wiki_pages: number; sources: number }
  search: {
    chunks: number
    embeddings: number
    fts_rows: number
    embedding_model: string
    embedding_dim: number
    enabled: boolean
  }
  graph: {
    references: number
    cites: number
    links: number
    sources_connected: number
    sources_orphan: number
  }
}

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/40 p-3">
      <div className="text-lg font-semibold tabular-nums text-foreground">
        {typeof value === 'number' ? value.toLocaleString() : value}
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">{label}</div>
      {hint && <div className="mt-0.5 text-[11px] text-muted-foreground/70">{hint}</div>}
    </div>
  )
}

export default function SettingsPage() {
  const router = useRouter()
  const token = useUserStore((s) => s.accessToken)
  const [usage, setUsage] = React.useState<Usage | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [configCopied, setConfigCopied] = React.useState(false)
  const [stats, setStats] = React.useState<IndexStats | null>(null)
  const isLocal = process.env.NEXT_PUBLIC_MODE === 'local'

  const oauthConfigJson = buildOAuthMcpConfig()

  React.useEffect(() => {
    if (!token) return
    apiFetch<Usage>('/v1/usage', token)
      .then((u) => setUsage(u))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [token])

  React.useEffect(() => {
    if (!token || !isLocal) return
    apiFetch<IndexStats>('/v1/index-stats', token)
      .then(setStats)
      .catch(() => {})
  }, [token, isLocal])

  const handleCopyConfig = async () => {
    try {
      await navigator.clipboard.writeText(oauthConfigJson)
      setConfigCopied(true)
      setTimeout(() => setConfigCopied(false), 2000)
    } catch {
      console.error('Failed to copy')
    }
  }

  return (
    <div className="max-w-2xl mx-auto p-8">
      <div className="flex items-center gap-3 mb-8">
        <button
          onClick={() => router.back()}
          className="p-1 rounded-md hover:bg-accent transition-colors cursor-pointer text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
        </button>
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
      </div>

      {/* Index (local mode) */}
      {stats && (
        <section>
          <h2 className="text-base font-medium">Index</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Local SQLite index, hybrid search, and the reference graph for this workspace.
          </p>

          <div className="mt-4 grid grid-cols-3 gap-3">
            <Stat label="Documents" value={stats.documents.total} />
            <Stat label="Wiki pages" value={stats.documents.wiki_pages} />
            <Stat label="Sources" value={stats.documents.sources} />
          </div>

          <h3 className="mt-6 mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Search · hybrid FTS5 + vector
          </h3>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Chunks" value={stats.search.chunks} />
            <Stat label="Embeddings" value={stats.search.embeddings} />
            <Stat
              label="Status"
              value={stats.search.enabled ? 'Active' : 'Empty'}
              hint={`${stats.search.embedding_model} · ${stats.search.embedding_dim}d`}
            />
          </div>

          <h3 className="mt-6 mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Reference graph
          </h3>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Citations" value={stats.graph.cites} />
            <Stat label="Wiki links" value={stats.graph.links} />
            <Stat
              label="Sources cited"
              value={`${stats.graph.sources_connected} / ${stats.documents.sources}`}
              hint={stats.graph.sources_orphan > 0 ? `${stats.graph.sources_orphan.toLocaleString()} orphan` : 'all linked'}
            />
          </div>
        </section>
      )}

      {stats && <div className="h-px bg-border my-8" />}

      {/* Usage */}
      {usage && (
        <section>
          <h2 className="text-base font-medium">Usage</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {usage.document_count} document{usage.document_count !== 1 ? 's' : ''} uploaded
          </p>
          <div className="mt-4 space-y-4">
            <div>
              <div className="flex items-center justify-between text-sm mb-1.5">
                <span className="text-muted-foreground">Storage</span>
                <span className="font-mono text-xs">
                  {formatBytes(usage.total_storage_bytes)} / {formatBytes(usage.max_storage_bytes)}
                </span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className={cn(
                    'h-full rounded-full transition-all',
                    usage.total_storage_bytes / usage.max_storage_bytes > 0.9
                      ? 'bg-destructive'
                      : usage.total_storage_bytes / usage.max_storage_bytes > 0.7
                        ? 'bg-yellow-500'
                        : 'bg-primary'
                  )}
                  style={{ width: `${Math.min(100, (usage.total_storage_bytes / usage.max_storage_bytes) * 100)}%` }}
                />
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between text-sm mb-1.5">
                <span className="text-muted-foreground">OCR Pages</span>
                <span className="font-mono text-xs">
                  {usage.total_pages.toLocaleString()} / {usage.max_pages.toLocaleString()}
                </span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className={cn(
                    'h-full rounded-full transition-all',
                    usage.total_pages / usage.max_pages > 0.9
                      ? 'bg-destructive'
                      : usage.total_pages / usage.max_pages > 0.7
                        ? 'bg-yellow-500'
                        : 'bg-primary'
                  )}
                  style={{ width: `${Math.min(100, (usage.total_pages / usage.max_pages) * 100)}%` }}
                />
              </div>
            </div>
          </div>
        </section>
      )}

      {usage && <div className="h-px bg-border my-8" />}

      {/* MCP Config */}
      <section>
        <h2 className="text-base font-medium">
          {process.env.NEXT_PUBLIC_MODE === 'local' ? 'Connect Claude' : 'Connect via OAuth'}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          {process.env.NEXT_PUBLIC_MODE === 'local'
            ? 'Run this command to get the Claude Desktop / Claude Code MCP config for this workspace:'
            : 'Add this configuration to your MCP client. On first connection, it should prompt you to sign in with Supabase.'
          }
        </p>
        <div className="relative mt-4">
          <pre className="rounded-lg bg-muted border border-border p-4 text-sm font-mono overflow-x-auto text-foreground">
            {process.env.NEXT_PUBLIC_MODE === 'local'
              ? 'llmwiki mcp-config <workspace-path>'
              : oauthConfigJson
            }
          </pre>
          {process.env.NEXT_PUBLIC_MODE !== 'local' && (
            <button
              onClick={handleCopyConfig}
              className={cn(
                'absolute top-3 right-3 flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs transition-colors cursor-pointer',
                configCopied
                  ? 'bg-green-500/10 text-green-600 dark:text-green-400'
                  : 'bg-background border border-border text-muted-foreground hover:text-foreground hover:bg-accent'
              )}
            >
              {configCopied ? <><Check size={12} />Copied</> : <><Copy size={12} />Copy</>}
            </button>
          )}
        </div>
        {process.env.NEXT_PUBLIC_MODE !== 'local' && (
          <p className="mt-3 text-xs text-muted-foreground">
            MCP URL:
            {' '}
            <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">{MCP_URL}</code>
          </p>
        )}
      </section>
    </div>
  )
}
