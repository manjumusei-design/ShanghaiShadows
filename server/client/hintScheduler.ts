export interface TutorialHint {
  hint_id: string
  stage_id: string
  room_id?: string
  payload: string
  immediate: boolean
}

export interface HintSchedulerOptions {
  delayMs?: number
  now?: () => number
  setTimeoutFn?: (fn: () => void, ms: number) => unknown
  clearTimeoutFn?: (handle: unknown) => void
  onShow?: (hint: TutorialHint) => void
}

const DEFAULT_DELAY_MS = 10_000

export class HintScheduler {
  private pending: TutorialHint | null = null
  private shown: string | null = null 
  private timerHandle: unknown = null
  private readonly delayMs: number
  private readonly now: () => number
  private readonly setTimeoutFn: (fn: () => void, ms: number) => unknown
  private readonly clearTimeoutFn: (handle: unknown) => void
  private readonly onShow: ((hint: TutorialHint) => void) | undefined

  constructor(options: HintSchedulerOptions = {}) {
    this.delayMs = options.delayMs ?? DEFAULT_DELAY_MS
    this.now = options.now ?? (() => Date.now())
    this.setTimeoutFn = options.setTimeoutFn ?? ((fn, ms) => setTimeout(fn, ms))
    this.clearTimeoutFn = options.clearTimeoutFn ?? ((h) => clearTimeout(h as ReturnType<typeof setTimeout>))
    this.onShow = options.onShow
  }

  enqueue(hint: TutorialHint): void {
    if (this.shown === hint.hint_id) {
      return
    }
    this.clearTimer()
    if (hint.immediate) {
      this.shown = hint.hint_id
      this.pending = null
      this.onShow?.(hint)
      return
    }
    this.pending = hint
    this.schedule()
  }

  restart(): void {
    if (!this.pending) return
    this.clearTimer()
    this.schedule()
  }

  onRoomChange(newRoomKey: string): void {
    if (!this.pending) return
    if (this.pending.room_id && this.pending.room_id !== newRoomKey) {

      this.clear()
    }
  }

  clear(): void {
    this.clearTimer()
    this.pending = null
  }


  markShown(hintId: string): void {
    this.shown = hintId
    this.clearTimer()
    this.pending = null
  }

  reset(): void {
    this.clear()
    this.shown = null
  }

  getPending(): TutorialHint | null {
    return this.pending
  }

  getShown(): string | null {
    return this.shown
  }

  private schedule(): void {
    if (!this.pending) return
    const hint = this.pending
    this.timerHandle = this.setTimeoutFn(() => {
      if (this.pending === hint) {
        this.shown = hint.hint_id
        this.pending = null
        this.timerHandle = null
        this.onShow?.(hint)
      }
    }, this.delayMs)
  }

  private clearTimer(): void {
    if (this.timerHandle !== null) {
      this.clearTimeoutFn(this.timerHandle)
      this.timerHandle = null
    }
  }
}
