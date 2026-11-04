import { beforeEach, describe, expect, it } from 'vitest'
import { consumeReturnPath, rememberReturnPath, safeReturnPath, withReturnTo } from './returnTo'

const ORIGIN = 'https://llmwiki.app'

describe('safeReturnPath', () => {
  it('keeps same-origin paths with query and hash', () => {
    expect(safeReturnPath('/oauth/authorize?authorization_id=abc#x', ORIGIN)).toBe('/oauth/authorize?authorization_id=abc#x')
  })

  it.each([
    'https://evil.example/phish',
    '//evil.example/phish',
    '/\\evil.example',
    'javascript:alert(1)',
  ])('rejects off-origin destination %s', (raw) => {
    expect(safeReturnPath(raw, ORIGIN)).toBe('/wikis')
  })

  it('falls back when nothing was requested', () => {
    expect(safeReturnPath(null, ORIGIN)).toBe('/wikis')
  })
})

describe('remembered return path', () => {
  beforeEach(() => sessionStorage.clear())

  it('survives the OAuth round trip once', () => {
    rememberReturnPath('/oauth/authorize?authorization_id=abc')
    expect(consumeReturnPath()).toBe('/oauth/authorize?authorization_id=abc')
    expect(consumeReturnPath()).toBe('/wikis')
  })

  it('re-validates what was stored', () => {
    sessionStorage.setItem('llmwiki:returnTo', 'https://evil.example')
    expect(consumeReturnPath()).toBe('/wikis')
  })
})

describe('withReturnTo', () => {
  it('carries the destination across auth pages', () => {
    expect(withReturnTo('/signup', '/oauth/authorize?authorization_id=a&b=c'))
      .toBe('/signup?returnTo=%2Foauth%2Fauthorize%3Fauthorization_id%3Da%26b%3Dc')
    expect(withReturnTo('/signup', null)).toBe('/signup')
  })
})
