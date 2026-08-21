const REVEAL_TYPES = new Set(['room', 'npc', 'social', 'ambient', 'npc_ambient', 'combat_narration'])
const INSTANT_TEXT_STORAGE_KEY = 'ss_instant_text'

export function preferReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

export function instantTextPreference(): boolean {
  try {
    return typeof localStorage !== 'undefined' && localStorage.getItem(INSTANT_TEXT_STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

export function resolvesToInstantReveal(type: string): boolean {
  return !REVEAL_TYPES.has(type) || instantTextPreference() || prefersReducedMotion()
}