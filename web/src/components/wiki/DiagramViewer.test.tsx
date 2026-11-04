import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DiagramViewer } from './DiagramViewer'

let resolvedTheme: 'light' | 'dark' = 'light'

vi.mock('next-themes', () => ({
  useTheme: () => ({ resolvedTheme }),
}))

function iframeSrcdoc(): string {
  return screen.getByTitle('Diagram').getAttribute('srcdoc') ?? ''
}

beforeEach(() => {
  resolvedTheme = 'light'
})

afterEach(cleanup)

describe('DiagramViewer', () => {
  it('uses the app dark canvas inside the isolated iframe', () => {
    resolvedTheme = 'dark'
    render(
      <DiagramViewer
        content="<svg viewBox='0 0 10 10'></svg>"
        type="svg"
        onClose={vi.fn()}
      />,
    )

    expect(iframeSrcdoc()).toContain('color-scheme: dark')
    expect(iframeSrcdoc()).toContain('background: hsl(20 14% 4%)')
    expect(iframeSrcdoc()).not.toContain('background: transparent')
  })

  it('keeps the warm paper canvas in light mode', () => {
    render(
      <DiagramViewer
        content="<svg viewBox='0 0 10 10'></svg>"
        type="svg"
        onClose={vi.fn()}
      />,
    )

    expect(iframeSrcdoc()).toContain('color-scheme: light')
    expect(iframeSrcdoc()).toContain('background: hsl(30 3% 96%)')
  })
})
