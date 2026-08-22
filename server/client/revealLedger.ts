const MAX_ENTRIES = 600

const revealedKeys = new Set<string>()
const insertionOrder: string[] = []

export function markRevealed(key: string): void {
  if (revealedKeys.has(key)) return
  revealedKeys.add(key)
  insertionOrder.push(key)
  while (insertionOrder.length > MAX_ENTRIES) {
    const evicted = insertionOrder.shift()
    if (evicted !== undefined) revealedKeys.delete(evicted)
  }
}

export function isRevealed(key: string): boolean {
  return revealedKeys.has(key)
}

export function resetRevealLedger(): void {
  revealedKeys.clear()
  insertionOrder.length = 0
}
