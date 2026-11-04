'use client'

import * as React from 'react'
import Link from 'next/link'
import {
  Archive,
  BookOpen,
  FilePenLine,
  FilePlus2,
  History,
  Loader2,
  RotateCcw,
  Trash2,
  Upload,
} from 'lucide-react'
import { useKBEvents } from '@/hooks/useKBEvents'
import {
  activityCountLabel,
  activityVerb,
  coalesceKnowledgeBaseEvents,
  formatActivityTime,
  groupActivityByDay,
  type ActivityDisplayItem,
} from '@/lib/kbEvents'
import type { DocumentListItem } from '@/lib/types'

interface RecentChangesProps {
  kbId: string
  kbSlug: string
  kbName: string
  documents: DocumentListItem[]
  refreshKey: string
  onWikiNavigate: (path: string, docNumber?: number | null) => void
  planSlot?: React.ReactNode
}

function EventGlyph({ event }: { event: ActivityDisplayItem }) {
  const className = 'size-3.5'
  switch (event.event_type) {
    case 'tracking.started': return <History className={className} />
    case 'wiki.created': return <BookOpen className={className} />
    case 'page.created': return <FilePlus2 className={className} />
    case 'page.updated': return <FilePenLine className={className} />
    case 'page.archived': return <Archive className={className} />
    case 'page.restored': return <RotateCcw className={className} />
    case 'page.deleted': return <Trash2 className={className} />
    case 'source.added': return <Upload className={className} />
    case 'source.updated': return <FilePenLine className={className} />
    case 'source.deleted': return <Trash2 className={className} />
  }
}

function TimelineSkeleton() {
  return (
    <div className="mt-12" aria-label="Loading recent changes">
      <div className="mb-3 h-3 w-14 rounded bg-muted/60" />
      {[0, 1, 2, 3].map((index) => (
        <div key={index} className="flex items-center gap-4 py-1">
          <div className="h-3 w-11 rounded bg-muted/50" />
          <div className="size-7 rounded-full bg-muted/50" />
          <div className="h-3 rounded bg-muted/50" style={{ width: `${42 + index * 7}%` }} />
        </div>
      ))}
    </div>
  )
}

function SubjectLink({
  event,
  kbSlug,
  documents,
  onWikiNavigate,
}: {
  event: ActivityDisplayItem
  kbSlug: string
  documents: DocumentListItem[]
  onWikiNavigate: RecentChangesProps['onWikiNavigate']
}) {
  const current = event.document_id
    ? documents.find((document) => document.id === event.document_id && !document.archived)
    : null
  const unavailable = event.event_type === 'page.archived'
    || event.event_type === 'page.deleted'
    || event.event_type === 'source.deleted'
    || !current

  if (unavailable || current.document_number == null) {
    return <span className="font-medium text-foreground/75">{event.subject_title}</span>
  }

  if (event.subject_kind === 'wiki_page') {
    const currentPath = (current.path + current.filename).replace(/^\/wiki\/?/, '')
    return (
      <Link
        href={`/wikis/${kbSlug}?p=${current.document_number}`}
        onClick={(clickEvent) => {
          clickEvent.preventDefault()
          onWikiNavigate(currentPath, current.document_number)
        }}
        className="font-medium text-foreground underline decoration-border underline-offset-4 transition-colors hover:decoration-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
      >
        {event.subject_title}
      </Link>
    )
  }

  return (
    <Link
      href={`/wikis/${kbSlug}/files?doc=${current.document_number}`}
      className="font-medium text-foreground underline decoration-border underline-offset-4 transition-colors hover:decoration-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
    >
      {event.subject_title}
    </Link>
  )
}

function TimelineRow(props: {
  event: ActivityDisplayItem
  kbSlug: string
  documents: DocumentListItem[]
  onWikiNavigate: RecentChangesProps['onWikiNavigate']
}) {
  const { event } = props
  const verb = activityVerb(event)
  const countLabel = activityCountLabel(event)
  const standalone = event.subject_kind === 'wiki'

  return (
    <div className="grid grid-cols-[3.25rem_1.25rem_minmax(0,1fr)] items-baseline gap-2.5 py-1 sm:grid-cols-[3.75rem_1.25rem_minmax(0,1fr)]">
      <time
        dateTime={event.occurred_at}
        className="text-[11px] tabular-nums text-muted-foreground/55"
      >
        {formatActivityTime(event.occurred_at)}
      </time>
      <span className="flex items-center self-center text-muted-foreground/60">
        <EventGlyph event={event} />
      </span>
      <div className="flex min-w-0 items-baseline gap-1.5 text-[13px] leading-6">
        {standalone ? (
          <span className="text-foreground/80">{verb}</span>
        ) : (
          <>
            <span className="shrink-0 text-muted-foreground">{verb}</span>
            <span className="min-w-0 truncate">
              <SubjectLink {...props} />
            </span>
          </>
        )}
        {countLabel && (
          <span className="shrink-0 whitespace-nowrap text-[11px] text-muted-foreground/45">
            {countLabel}
          </span>
        )}
      </div>
    </div>
  )
}

export function RecentChanges({
  kbId,
  kbSlug,
  kbName,
  documents,
  refreshKey,
  onWikiNavigate,
  planSlot,
}: RecentChangesProps) {
  const {
    events: rawEvents,
    loading,
    loadingMore,
    error,
    hasMore,
    loadMore,
    retry,
  } = useKBEvents(kbId, true, refreshKey)
  const events = React.useMemo(() => coalesceKnowledgeBaseEvents(rawEvents), [rawEvents])
  const groups = React.useMemo(() => groupActivityByDay(events), [events])

  return (
    <div className="h-full overflow-y-auto bg-background">
      <div className="mx-auto w-full max-w-4xl px-6 pb-16 pt-8 sm:px-10 sm:pt-10">
        <header>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground/55">
            {kbName}
          </p>
          <h1 className="text-xl font-semibold tracking-tight text-foreground">
            Recent changes
          </h1>
        </header>

        {planSlot && <div className="mt-6">{planSlot}</div>}

        {loading && rawEvents.length === 0 ? (
          <TimelineSkeleton />
        ) : groups.length === 0 ? (
          <div className="mt-16 border-t border-border pt-8">
            <History className="mb-4 size-6 text-muted-foreground/30" />
            <h2 className="text-sm font-medium text-foreground">No activity yet</h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              New pages, edits, and sources will appear here.
            </p>
          </div>
        ) : (
          <div className="mt-6 space-y-5">
            {groups.map((group) => (
              <section key={group.key} aria-labelledby={`activity-${group.key}`}>
                <h2
                  id={`activity-${group.key}`}
                  className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground/55"
                >
                  {group.label}
                </h2>
                <div>
                  {group.items.map((event) => (
                    <TimelineRow
                      key={event.id}
                      event={event}
                      kbSlug={kbSlug}
                      documents={documents}
                      onWikiNavigate={onWikiNavigate}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}

        {error && (
          <div className="mt-8 flex items-center gap-3 text-xs text-muted-foreground" role="status">
            <span>{error}</span>
            <button
              type="button"
              onClick={retry}
              className="cursor-pointer font-medium text-foreground underline decoration-border underline-offset-4"
            >
              Retry
            </button>
          </div>
        )}

        {hasMore && (
          <div className="mt-10 border-t border-border pt-6">
            <button
              type="button"
              onClick={loadMore}
              disabled={loadingMore}
              className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-md px-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-default disabled:opacity-50"
            >
              {loadingMore && <Loader2 className="size-3 animate-spin" />}
              Load older
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
