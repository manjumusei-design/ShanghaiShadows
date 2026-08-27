export interface OverheardTurn {
  speaker?: string
  text?: string
  delay_ms?: number
}

export interface OverheardEntry {
  id: string
  room_id: string
  turns?: OverheardTurn[]
  instant?: boolean
}

export const OVERHEARD_INITIAL_BEAT_MS = 1000
export const OVERHEARD_MIN_TURN_DELAY_MS = 2200
export const OVERHEARD_POST_EXCHANGE_HOLD_MS = 1200
export const OVERHEARD_CHARACTER_DELAY_MS = 24

export interface OverheardSchedulerOptions {
  initialBeatMs?: number
  minTurnDelayMs?: number
  postExchangeHoldMs?: number
  characterDelayMs?: number
}

export interface OverheardSchedulerHooks<E extends OverheardEntry> {
  onEnqueue: (entry: E) => void
  onRevealTurn: (entry: E, turnIndex: number, text: string, complete: boolean) => void
  onComplete: (entry: E) => void
}

export function createOverheardScheduler<E extends OverheardEntry>(
  hooks: OverheardSchedulerHooks<E>,
  options: OverheardSchedulerOptions = {},
) {
  const initialBeatMs = options.initialBeatMs ?? OVERHEARD_INITIAL_BEAT_MS
  const minTurnDelayMs = options.minTurnDelayMs ?? OVERHEARD_MIN_TURN_DELAY_MS
  const postExchangeHoldMs = options.postExchangeHoldMs ?? OVERHEARD_POST_EXCHANGE_HOLD_MS
  const characterDelayMs = options.characterDelayMs ?? OVERHEARD_CHARACTER_DELAY_MS

  const seenIds = new Set<string>()
  const queue: E[] = []
  let active: E | null = null
  let timer: ReturnType<typeof setTimeout> | null | null
  let generation = 0


  const turnWaitMs = (turn: OverheardTurn | undefined) =>
    Math.max(turn?.delay_ms ?? minTurnDelayMs, minTurnDelayMs)

  const clearTimer = () => {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  const pump = () => {
    if (active || timer !== null || queue.length === 0) return
    active = queue.shift() ?? null
    if (!active) return

    const entry = active
    const turns = entry.turns ?? []
    const activeGeneration = generation
    const isCurrent = () => activeGeneration === generation && active === entry
    if (entry.instant || turns.length === 0) {
      turns.forEach((turn, index) => hooks.onRevealTurn(entry, index, turn.text || "", true))
      hooks.onComplete(entry)
      active = null
      pump()
      return
    }

    const revealTurn = (turnIndex: number) => {
      if (!isCurrent()) return
      const turn = turns[turnIndex]
      const fullText = turn?.text || ""
      const turnStartedAt = Date.now()
      let position = 0
      hooks.onTurnStart?.(entry, turnIndex)

      const step = () => {
        if (!isCurrent()) return
        timer = null
        position += 1
        const complete = position >= fullText.length
        hooks.onRevealTurn(entry, turnIndex, fullText.slice(0, position), complete)
        if (!complete) {
          timer = setTimeout(step, characterDelayMs)
          return
        }
        if (turnIndex >= turns.length - 1) {
          timer = setTimeout(() => {
            if (!isCurrent()) return
            timer = null
            hooks.onComplete(entry)
            active = null
            pump()
          }, postExchangeHoldMs)
          return
        }
        const wait = turnWaitMs(turns[turnIndex + 1])
        const remaining = Math.max(0, wait - (Date.now() - turnStartedAt))
        timer = setTimeout(() => {
          if (!isCurrent()) return
          timer = null
          revealTurn(turnIndex + 1)
        }, remaining)
      }

      if (!fullText.length) {
        hooks.onRevealTurn(entry, turnIndex, "", true)
        if (turnIndex >= turns.length - 1) {
          timer = setTimeout(() => {
            if (!isCurrent()) return
            timer = null
            hooks.onComplete(entry)
            active = null
            pump()
          }, postExchangeHoldMs)
          return
        }
        const wait = turnWaitMs(turns[turnIndex + 1])
        timer = setTimeout(() => {
          if (!isCurrent()) return
          timer = null
          revealTurn(turnIndex + 1)
        }, wait)
        return
      }
      step()
    }

    timer = setTimeout(() => {
      if (!isCurrent()) return
      timer = null
      revealTurn(0)
    }, initialBeatMs)
  }

  const enqueue = (entries: OverheardEntry[] | null | undefined) => {
    for (const raw of entries ?? []) {
      const entry = raw as E
      if (!entry || !entry.id || seenIds.has(entry.id)) continue
      seenIds.add(entry.id)
      queue.push(entry)
      hooks.onEnqueue(entry)
    }
    pump()
  }

  const clear = () => {
    generation += 1
    clearTimer()
    queue.length = 0
    seenIds.clear()
    active = null
  }

  return { enqueue, clear, dispose: clear }
}
