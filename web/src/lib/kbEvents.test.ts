import { describe, expect, it } from 'vitest'
import {
  activityVerb,
  coalesceKnowledgeBaseEvents,
  groupActivityByDay,
} from '@/lib/kbEvents'
import type { KnowledgeBaseEvent } from '@/lib/types'

function event(
  id: string,
  occurredAt: string,
  overrides: Partial<KnowledgeBaseEvent> = {},
): KnowledgeBaseEvent {
  return {
    id,
    event_type: 'page.updated',
    subject_kind: 'wiki_page',
    document_id: 'doc-1',
    document_number: 7,
    document_version: Number(id),
    subject_title: 'Retrieval design',
    subject_path: '/wiki/retrieval.md',
    metadata: { changes: ['content'] },
    occurred_at: occurredAt,
    ...overrides,
  }
}

describe('coalesceKnowledgeBaseEvents', () => {
  it('orders by raw event id and merges adjacent edits across a loaded-page boundary', () => {
    const result = coalesceKnowledgeBaseEvents([
      event('101', '2026-07-16T10:09:00Z', { metadata: { changes: ['title'] } }),
      event('100', '2026-07-16T10:00:00Z'),
      event('102', '2026-07-16T10:18:00Z', { metadata: { changes: ['tags'] } }),
    ])

    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('102')
    expect(result[0].event_count).toBe(3)
    expect(result[0].metadata.changes).toEqual(['tags', 'title', 'content'])
    expect(activityVerb(result[0])).toBe('Updated')
  })

  it('does not merge across an intervening raw event', () => {
    const result = coalesceKnowledgeBaseEvents([
      event('3', '2026-07-16T10:02:00Z'),
      event('2', '2026-07-16T10:01:00Z', {
        event_type: 'source.added',
        subject_kind: 'source',
        document_id: 'source-1',
      }),
      event('1', '2026-07-16T10:00:00Z'),
    ])

    expect(result).toHaveLength(3)
  })

  it('keeps edits separate across local-day boundaries', () => {
    const daySplit = coalesceKnowledgeBaseEvents([
      event('2', new Date(2026, 6, 16, 0, 1).toISOString()),
      event('1', new Date(2026, 6, 15, 23, 59).toISOString()),
    ])
    expect(daySplit).toHaveLength(2)
  })
})

describe('groupActivityByDay', () => {
  it('uses browser-local Today, Yesterday, and absolute labels without reordering', () => {
    const now = new Date(2026, 6, 16, 12, 0)
    const display = coalesceKnowledgeBaseEvents([
      event('3', new Date(2026, 6, 16, 9, 0).toISOString(), { document_id: 'a' }),
      event('2', new Date(2026, 6, 15, 9, 0).toISOString(), { document_id: 'b' }),
      event('1', new Date(2026, 6, 12, 9, 0).toISOString(), { document_id: 'c' }),
    ])

    const groups = groupActivityByDay(display, now)
    expect(groups.map((group) => group.label)).toEqual(['Today', 'Yesterday', 'July 12'])
    expect(groups.flatMap((group) => group.items.map((item) => item.id))).toEqual(['3', '2', '1'])
  })
})
