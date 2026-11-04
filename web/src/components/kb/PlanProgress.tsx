'use client'

import type { PlanSummary } from '@/lib/planTasks'

export function PlanProgress({ summary, onOpen }: { summary: PlanSummary; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full cursor-pointer rounded-lg border border-border/60 p-4 text-left transition-colors hover:bg-accent/50"
    >
      <p className="mb-3 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground/55">
        Plan
      </p>
      <div className="flex items-center gap-3">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full bg-foreground/30 transition-[width]"
            style={{ width: `${Math.round((summary.done / summary.total) * 100)}%` }}
          />
        </div>
        <span className="text-[11px] text-muted-foreground/50 tabular-nums">
          {summary.done}/{summary.total}
        </span>
      </div>
      <div className="mt-3 space-y-1">
        {summary.stages.map((stage, index) => (
          <div key={index} className="flex items-baseline justify-between gap-4 text-xs">
            <span className="min-w-0 truncate text-muted-foreground">{stage.title || 'Tasks'}</span>
            <span className="shrink-0 tabular-nums text-muted-foreground/60">
              {stage.done}/{stage.total}
              {stage.counts.blocked > 0 && (
                <span className="text-amber-500"> · {stage.counts.blocked} blocked</span>
              )}
            </span>
          </div>
        ))}
      </div>
    </button>
  )
}
