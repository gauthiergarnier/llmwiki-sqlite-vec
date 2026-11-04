import { describe, expect, it } from 'vitest'

import { extractTocFromMarkdown, rehypeHeadingIds, remarkTaskStatus, stripLegacyQuizWrapper } from './WikiContent'

describe('extractTocFromMarkdown quiz terminology', () => {
  it('displays a legacy Checkpoint heading as Quiz without changing its anchor', () => {
    expect(extractTocFromMarkdown('## Checkpoint\n\n### Review')).toEqual([
      { id: 'checkpoint', text: 'Quiz', level: 2 },
      { id: 'review', text: 'Review', level: 3 },
    ])
  })

  it('removes the redundant generated wrapper directly around a quiz', () => {
    const content = `## Checkpoint

Try to answer without looking back.

\`\`\`quiz
questions:
  - prompt: Question?
    options: [One, Two]
    answer: 0
\`\`\`
`
    const normalized = stripLegacyQuizWrapper(content)

    expect(normalized).not.toContain('Checkpoint')
    expect(normalized).not.toContain('Try to answer without looking back.')
    expect(normalized).toContain('```quiz')
    expect(extractTocFromMarkdown(normalized)).toEqual([])
  })
})

interface TestNode {
  type: string
  value?: string
  checked?: boolean | null
  children?: TestNode[]
  data?: { hProperties?: Record<string, unknown> }
}

function taskItem(text: string, checked: boolean | null = null): TestNode {
  return {
    type: 'listItem',
    checked,
    children: [{ type: 'paragraph', children: [{ type: 'text', value: text }] }],
  }
}

function taskStatusOf(node: TestNode): unknown {
  return node.data?.hProperties?.['data-task']
}

describe('remarkTaskStatus', () => {
  const transform = remarkTaskStatus()

  it('tags gfm-parsed checkboxes as done and todo', () => {
    const done = taskItem('shipped', true)
    const todo = taskItem('pending', false)
    const root: TestNode = { type: 'root', children: [{ type: 'list', children: [done, todo] }] }

    transform(root)

    expect(taskStatusOf(done)).toBe('done')
    expect(taskStatusOf(todo)).toBe('todo')
  })

  it('tags [~] as in_progress and strips the marker', () => {
    const item = taskItem('[~] Ship it')

    transform(item)

    expect(taskStatusOf(item)).toBe('in_progress')
    expect(item.children?.[0].children?.[0].value).toBe('Ship it')
  })

  it('tags [!] as blocked, including nested list items', () => {
    const nested = taskItem('[!] Blocked on API')
    const parent = taskItem('[~] Parent task')
    parent.children!.push({ type: 'list', children: [nested] })

    transform({ type: 'root', children: [{ type: 'list', children: [parent] }] })

    expect(taskStatusOf(parent)).toBe('in_progress')
    expect(taskStatusOf(nested)).toBe('blocked')
    expect(nested.children?.[0].children?.[0].value).toBe('Blocked on API')
  })

  it('leaves markerless items and [!]-without-space text untouched', () => {
    const plain = taskItem('just a bullet')
    const callout = taskItem('[!]Note this is not a task')

    transform({ type: 'root', children: [{ type: 'list', children: [plain, callout] }] })

    expect(taskStatusOf(plain)).toBeUndefined()
    expect(taskStatusOf(callout)).toBeUndefined()
    expect(callout.children?.[0].children?.[0].value).toBe('[!]Note this is not a task')
  })
})

// Fork: duplicate headings must get unique anchors, identical in the TOC and the DOM.
describe('heading anchors', () => {
  type Node = { type: string; tagName?: string; value?: string; properties?: Record<string, unknown>; children?: Node[] }
  const h = (level: number, text: string, id?: string): Node => ({
    type: 'element',
    tagName: `h${level}`,
    properties: id ? { id } : {},
    children: [{ type: 'text', value: text }],
  })
  const idsOf = (tree: Node): unknown[] =>
    (tree.children ?? []).filter((n) => n.tagName?.startsWith('h')).map((n) => n.properties?.id)

  it('suffixes duplicate headings -1, -2 in the TOC', () => {
    const md = '## Billing / commercial model\n\n## Notes\n\n### Billing / commercial model\n\n## Billing / commercial model'
    expect(extractTocFromMarkdown(md).map((i) => i.id)).toEqual([
      'billing-commercial-model',
      'notes',
      'billing-commercial-model-1',
      'billing-commercial-model-2',
    ])
  })

  it('assigns the same ids to rendered headings, counting h1 and h4 too', () => {
    const md = '# Intro\n\n## Intro\n\n#### Deep\n\n### Deep\n\n## Intro'
    const tree: Node = {
      type: 'root',
      children: [h(1, 'Intro'), h(2, 'Intro'), h(4, 'Deep'), h(3, 'Deep'), h(2, 'Intro')],
    }
    rehypeHeadingIds()(tree)
    expect(idsOf(tree)).toEqual(['intro', 'intro-1', 'deep', 'deep-1', 'intro-2'])
    expect(extractTocFromMarkdown(md).map((i) => i.id)).toEqual(['intro-1', 'deep-1', 'intro-2'])
  })

  it('leaves ids set by other plugins alone (GFM footnote label)', () => {
    const tree: Node = { type: 'root', children: [h(2, 'Footnotes', 'footnote-label')] }
    rehypeHeadingIds()(tree)
    expect(idsOf(tree)).toEqual(['footnote-label'])
  })

  it('never collides a generated suffix with a literal heading', () => {
    const md = '## Pages updated\n\n## Pages updated 2\n\n## Pages updated\n\n## Pages updated'
    const ids = extractTocFromMarkdown(md).map((i) => i.id)
    expect(ids).toEqual(['pages-updated', 'pages-updated-2', 'pages-updated-1', 'pages-updated-3'])
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('ignores heading-like lines inside fenced code', () => {
    const md = '## Real\n\n```bash\n## not a heading\n```\n\n## Real'
    expect(extractTocFromMarkdown(md).map((i) => i.id)).toEqual(['real', 'real-1'])
  })
})

// Fork: prices must never render as math; \( \) and $$ still do.
describe('math rendering', () => {
  it('renders only explicit math, never currency', async () => {
    const React = await import('react')
    const { renderToString } = await import('react-dom/server')
    const { WikiContent } = await import('./WikiContent')
    const md = 'A **$50k** contract = **$5k** metered + $1k/mo (5–10%).\n\nInline \\(x^2\\) and $$y_1$$.'
    const html = renderToString(
      React.createElement(WikiContent, { content: md, title: 'T', onNavigate: () => {} }),
    )
    const tex = [...html.matchAll(/<annotation encoding="application\/x-tex">([\s\S]*?)<\/annotation>/g)].map((m) => m[1])
    expect(tex).toEqual(['x^2', 'y_1'])
    expect(html).toContain('$50k')
    expect(html).toContain('$1k/mo')
  })
})
