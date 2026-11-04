import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import type { WikiHighlightsApi } from '@/hooks/useWikiHighlights'
import { WikiHighlighter } from './WikiHighlighter'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

const originalRangeRect = Object.getOwnPropertyDescriptor(Range.prototype, 'getBoundingClientRect')

beforeAll(() => {
  Object.defineProperty(Range.prototype, 'getBoundingClientRect', {
    configurable: true,
    value: () => new DOMRect(120, 80, 64, 18),
  })
})

afterAll(() => {
  if (originalRangeRect) {
    Object.defineProperty(Range.prototype, 'getBoundingClientRect', originalRangeRect)
  } else {
    Reflect.deleteProperty(Range.prototype, 'getBoundingClientRect')
  }
})

afterEach(() => {
  cleanup()
  window.getSelection()?.removeAllRanges()
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

function setupSelection() {
  const scroll = document.createElement('div')
  const content = document.createElement('div')
  const text = document.createTextNode('Alpha beta gamma')
  content.appendChild(text)
  scroll.appendChild(content)
  document.body.appendChild(scroll)

  Object.defineProperty(scroll, 'clientWidth', { configurable: true, value: 800 })
  Object.defineProperty(scroll, 'scrollTop', { configurable: true, value: 0 })

  const api: WikiHighlightsApi = {
    highlights: [],
    saveHighlight: vi.fn().mockResolvedValue(undefined),
    updateComment: vi.fn().mockResolvedValue(undefined),
    removeHighlight: vi.fn().mockResolvedValue(undefined),
  }

  render(
    <WikiHighlighter
      scrollRef={{ current: scroll }}
      contentRef={{ current: content }}
      documentId="doc-1"
      contentKey="page-1"
      api={api}
    />,
  )

  const range = document.createRange()
  range.setStart(text, 0)
  range.setEnd(text, 5)
  const selection = window.getSelection()
  selection?.removeAllRanges()
  selection?.addRange(range)
  fireEvent.pointerUp(content)

  return { api }
}

describe('WikiHighlighter selection actions', () => {
  it('keeps selection transient until Highlight is chosen', async () => {
    const { api } = setupSelection()

    const highlightButton = await screen.findByRole('button', { name: 'Highlight selected text' })
    expect(api.saveHighlight).not.toHaveBeenCalled()

    fireEvent.click(highlightButton)

    expect(api.saveHighlight).toHaveBeenCalledWith(
      expect.objectContaining({ textStart: 0, textEnd: 5, textContent: 'Alpha' }),
      null,
    )
  })

  it('supports H to highlight and N to start a note', async () => {
    const first = setupSelection()
    await screen.findByRole('button', { name: 'Highlight selected text' })

    fireEvent.keyDown(document, { key: 'h' })
    expect(first.api.saveHighlight).toHaveBeenCalledWith(expect.any(Object), null)

    cleanup()
    document.body.innerHTML = ''
    window.getSelection()?.removeAllRanges()

    const second = setupSelection()
    await screen.findByRole('button', { name: 'Add note to selected text' })
    fireEvent.keyDown(document, { key: 'n' })

    const editor = await screen.findByRole('textbox')
    expect(second.api.saveHighlight).not.toHaveBeenCalled()
    fireEvent.change(editor, { target: { value: 'Worth revisiting' } })
    fireEvent.keyDown(editor, { key: 'Enter' })

    expect(second.api.saveHighlight).toHaveBeenCalledWith(
      expect.objectContaining({ textContent: 'Alpha' }),
      'Worth revisiting',
    )
  })

  it('copies without creating a highlight', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const { api } = setupSelection()

    fireEvent.click(await screen.findByRole('button', { name: 'Copy selected text' }))

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('Alpha'))
    expect(api.saveHighlight).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Copy selected text' })).toBeNull()
  })

  it('dismisses a pending selection with Escape without saving', async () => {
    const { api } = setupSelection()
    await screen.findByRole('button', { name: 'Highlight selected text' })

    fireEvent.keyDown(document, { key: 'Escape' })

    expect(api.saveHighlight).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Highlight selected text' })).toBeNull()
  })
})
