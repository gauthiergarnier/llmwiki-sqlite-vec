import { describe, expect, it } from 'vitest'
import { parsePlanTasks } from '@/lib/planTasks'

describe('parsePlanTasks', () => {
  it('groups tasks under h2 stages with per-status counts', () => {
    const summary = parsePlanTasks(`# Plan

## Stage one
- [ ] todo item
- [~] working item
- [x] done item
- [!] blocked item

## Stage two
- [x] shipped
`)

    expect(summary.total).toBe(5)
    expect(summary.done).toBe(2)
    expect(summary.stages).toHaveLength(2)
    expect(summary.stages[0]).toEqual({
      title: 'Stage one',
      counts: { todo: 1, in_progress: 1, done: 1, blocked: 1 },
      total: 4,
      done: 1,
    })
    expect(summary.stages[1].title).toBe('Stage two')
    expect(summary.stages[1].done).toBe(1)
  })

  it('collects tasks before the first heading into an untitled stage', () => {
    const summary = parsePlanTasks('- [x] early\n\n## Later\n- [ ] next\n')

    expect(summary.stages.map((s) => s.title)).toEqual(['', 'Later'])
    expect(summary.total).toBe(2)
    expect(summary.done).toBe(1)
  })

  it('accepts [X], alternate bullets, and nested indentation', () => {
    const summary = parsePlanTasks(`## Stage
* [X] star bullet
+ [ ] plus bullet
  - [~] nested child
`)

    expect(summary.stages[0].counts).toEqual({ todo: 1, in_progress: 1, done: 1, blocked: 0 })
  })

  it('ignores task-like lines inside code fences and frontmatter', () => {
    const summary = parsePlanTasks(`---
title: Plan
tags: [a]
---
## Stage
\`\`\`
- [ ] not a task
\`\`\`
- [x] real task
`)

    expect(summary.total).toBe(1)
    expect(summary.done).toBe(1)
  })

  it('does not treat h3 headings as stage boundaries or eat non-task brackets', () => {
    const summary = parsePlanTasks(`## Stage
- [ ] first
### Detail
- [x] second
- [!NOTE] callout, not a task
`)

    expect(summary.stages).toHaveLength(1)
    expect(summary.stages[0].total).toBe(2)
  })

  it('returns an empty summary when there are no tasks', () => {
    expect(parsePlanTasks('# Plan\n\nJust prose.\n')).toEqual({ stages: [], total: 0, done: 0 })
  })
})
