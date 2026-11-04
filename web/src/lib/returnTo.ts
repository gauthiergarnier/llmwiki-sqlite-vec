const DEFAULT_DESTINATION = '/wikis'
const STORAGE_KEY = 'llmwiki:returnTo'

export function safeReturnPath(raw: string | null, origin: string = window.location.origin): string {
  if (!raw || raw.includes('\\')) return DEFAULT_DESTINATION
  try {
    const url = new URL(raw, origin)
    if (url.origin !== origin) return DEFAULT_DESTINATION
    return `${url.pathname}${url.search}${url.hash}`
  } catch {
    return DEFAULT_DESTINATION
  }
}

// OAuth redirectTo must match the Supabase allowlist exactly, so the destination rides in sessionStorage.
export function rememberReturnPath(path: string): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, path)
  } catch {
    // Storage unavailable: the callback falls back to the default destination.
  }
}

export function consumeReturnPath(): string {
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY)
    sessionStorage.removeItem(STORAGE_KEY)
    return safeReturnPath(stored)
  } catch {
    return DEFAULT_DESTINATION
  }
}

export function withReturnTo(path: string, returnTo: string | null): string {
  return returnTo ? `${path}?returnTo=${encodeURIComponent(returnTo)}` : path
}
