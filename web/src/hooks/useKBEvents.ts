'use client'

import * as React from 'react'
import { apiFetch } from '@/lib/api'
import { useUserStore } from '@/stores'
import type { KnowledgeBaseEvent, KnowledgeBaseEventsPage } from '@/lib/types'

const PAGE_SIZE = 50

function mergeUnique(
  newest: KnowledgeBaseEvent[],
  existing: KnowledgeBaseEvent[],
): KnowledgeBaseEvent[] {
  const seen = new Set<string>()
  const merged: KnowledgeBaseEvent[] = []
  for (const event of [...newest, ...existing]) {
    if (seen.has(event.id)) continue
    seen.add(event.id)
    merged.push(event)
  }
  return merged
}

export function useKBEvents(
  knowledgeBaseId: string,
  enabled: boolean,
  refreshKey: string,
) {
  // Token rotation must not reset the feed; callbacks read the current token at call time.
  const hasToken = useUserStore((state) => Boolean(state.accessToken))
  const [events, setEvents] = React.useState<KnowledgeBaseEvent[]>([])
  const [nextCursor, setNextCursor] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(enabled)
  const [loadingMore, setLoadingMore] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const initializedRef = React.useRef(false)
  const loadedMoreRef = React.useRef(false)
  const refreshKeyRef = React.useRef(refreshKey)

  const endpoint = React.useCallback((before?: string) => {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE) })
    if (before) params.set('before', before)
    return `/v1/knowledge-bases/${knowledgeBaseId}/events?${params.toString()}`
  }, [knowledgeBaseId])

  const fetchInitial = React.useCallback(async (signal?: AbortSignal) => {
    const accessToken = useUserStore.getState().accessToken
    if (!enabled || !knowledgeBaseId || !accessToken) return
    setError(null)
    try {
      const page = await apiFetch<KnowledgeBaseEventsPage>(endpoint(), accessToken, { signal })
      setEvents(page.items)
      setNextCursor(page.next_cursor)
      initializedRef.current = true
      loadedMoreRef.current = false
    } catch (err) {
      if (signal?.aborted) return
      setError(err instanceof Error ? err.message : 'Failed to load recent changes')
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [enabled, endpoint, knowledgeBaseId])

  React.useEffect(() => {
    refreshKeyRef.current = refreshKey
    initializedRef.current = false
    loadedMoreRef.current = false
    if (!enabled || !knowledgeBaseId || !hasToken) {
      setEvents([])
      setNextCursor(null)
      setLoading(false)
      setError(null)
      return
    }

    const controller = new AbortController()
    setEvents([])
    setNextCursor(null)
    setLoading(true)
    fetchInitial(controller.signal)
    return () => controller.abort()
  }, [hasToken, enabled, fetchInitial, knowledgeBaseId])

  const refreshNewest = React.useCallback(async () => {
    const accessToken = useUserStore.getState().accessToken
    if (!enabled || !knowledgeBaseId || !accessToken || !initializedRef.current) return
    try {
      const page = await apiFetch<KnowledgeBaseEventsPage>(endpoint(), accessToken)
      setEvents((current) => mergeUnique(page.items, current))
      if (!loadedMoreRef.current) setNextCursor(page.next_cursor)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to refresh recent changes')
    }
  }, [enabled, endpoint, knowledgeBaseId])

  React.useEffect(() => {
    if (refreshKeyRef.current === refreshKey) return
    refreshKeyRef.current = refreshKey
    refreshNewest()
  }, [refreshKey, refreshNewest])

  const loadMore = React.useCallback(async () => {
    const accessToken = useUserStore.getState().accessToken
    if (!nextCursor || loadingMore || !accessToken) return
    setLoadingMore(true)
    setError(null)
    try {
      const page = await apiFetch<KnowledgeBaseEventsPage>(endpoint(nextCursor), accessToken)
      setEvents((current) => mergeUnique(current, page.items))
      setNextCursor(page.next_cursor)
      loadedMoreRef.current = true
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load older changes')
    } finally {
      setLoadingMore(false)
    }
  }, [endpoint, loadingMore, nextCursor])

  return {
    events,
    loading,
    loadingMore,
    error,
    hasMore: nextCursor !== null,
    loadMore,
    retry: () => fetchInitial(),
  }
}
