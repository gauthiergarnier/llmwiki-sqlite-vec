import type {
  KnowledgeBaseEvent,
  KnowledgeBaseEventChange,
} from '@/lib/types'

const COALESCE_WINDOW_MS = 10 * 60 * 1000
const UPDATE_EVENTS = new Set(['page.updated', 'source.updated'])

export interface ActivityDisplayItem extends KnowledgeBaseEvent {
  event_count: number
  first_occurred_at: string
}

export interface ActivityDayGroup {
  key: string
  label: string
  items: ActivityDisplayItem[]
}

function compareEventIdsDescending(a: KnowledgeBaseEvent, b: KnowledgeBaseEvent): number {
  try {
    const left = BigInt(a.id)
    const right = BigInt(b.id)
    return left === right ? 0 : left > right ? -1 : 1
  } catch {
    return b.id.localeCompare(a.id, undefined, { numeric: true })
  }
}

function localDayKey(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function calendarDayNumber(date: Date): number {
  return Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86_400_000)
}

function canCoalesce(group: ActivityDisplayItem, candidate: KnowledgeBaseEvent): boolean {
  if (!UPDATE_EVENTS.has(group.event_type) || !UPDATE_EVENTS.has(candidate.event_type)) return false
  if (!group.document_id || group.document_id !== candidate.document_id) return false
  if (group.subject_kind !== candidate.subject_kind) return false
  if (localDayKey(group.occurred_at) !== localDayKey(candidate.occurred_at)) return false

  const oldestInGroup = new Date(group.first_occurred_at).getTime()
  const candidateTime = new Date(candidate.occurred_at).getTime()
  const gap = oldestInGroup - candidateTime
  return Number.isFinite(oldestInGroup)
    && Number.isFinite(candidateTime)
    && gap >= 0
    && gap <= COALESCE_WINDOW_MS
}

function mergeChanges(
  current: KnowledgeBaseEventChange[] | undefined,
  incoming: KnowledgeBaseEventChange[] | undefined,
): KnowledgeBaseEventChange[] {
  return Array.from(new Set([...(current ?? []), ...(incoming ?? [])]))
}

export function coalesceKnowledgeBaseEvents(events: KnowledgeBaseEvent[]): ActivityDisplayItem[] {
  const sorted = [...events].sort(compareEventIdsDescending)
  const result: ActivityDisplayItem[] = []

  for (const event of sorted) {
    const previous = result[result.length - 1]
    if (previous && canCoalesce(previous, event)) {
      previous.event_count += 1
      previous.first_occurred_at = event.occurred_at
      previous.metadata = {
        ...previous.metadata,
        changes: mergeChanges(previous.metadata.changes, event.metadata.changes),
      }
      continue
    }

    result.push({
      ...event,
      metadata: {
        ...event.metadata,
        changes: event.metadata.changes ? [...event.metadata.changes] : undefined,
      },
      event_count: 1,
      first_occurred_at: event.occurred_at,
    })
  }

  return result
}

export function activityVerb(event: ActivityDisplayItem): string {
  switch (event.event_type) {
    case 'tracking.started': return 'Activity tracking started'
    case 'wiki.created': return 'Created this wiki'
    case 'page.created': return 'Created'
    case 'page.archived': return 'Archived'
    case 'page.restored': return 'Restored'
    case 'page.deleted': return 'Deleted'
    case 'source.added': return 'Added'
    case 'source.deleted': return 'Removed'
    case 'page.updated':
    case 'source.updated': {
      const changes = new Set(event.metadata.changes ?? [])
      if (changes.size === 1 && changes.has('title')) return 'Renamed'
      if (changes.size === 1 && changes.has('path')) return 'Moved'
      if ([...changes].every((change) => ['content', 'tags', 'date', 'properties'].includes(change))) {
        return 'Edited'
      }
      return 'Updated'
    }
  }
}

export function activityCountLabel(event: ActivityDisplayItem): string | null {
  if (event.event_count > 1) {
    const noun = activityVerb(event) === 'Edited' ? 'edits' : 'changes'
    return `${event.event_count} ${noun}`
  }
  const fileType = event.metadata.file_type
  return typeof fileType === 'string' && event.subject_kind === 'source'
    ? fileType.toUpperCase()
    : null
}

export function groupActivityByDay(
  events: ActivityDisplayItem[],
  now: Date = new Date(),
): ActivityDayGroup[] {
  const groups = new Map<string, ActivityDisplayItem[]>()
  for (const event of events) {
    const key = localDayKey(event.occurred_at)
    const group = groups.get(key)
    if (group) group.push(event)
    else groups.set(key, [event])
  }

  const todayNumber = calendarDayNumber(now)
  return Array.from(groups.entries()).map(([key, items]) => {
    const date = new Date(items[0].occurred_at)
    const difference = todayNumber - calendarDayNumber(date)
    let label: string
    if (difference === 0) label = 'Today'
    else if (difference === 1) label = 'Yesterday'
    else {
      label = new Intl.DateTimeFormat(undefined, {
        month: 'long',
        day: 'numeric',
        year: date.getFullYear() === now.getFullYear() ? undefined : 'numeric',
      }).format(date)
    }
    return { key, label, items }
  })
}

export function formatActivityTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
