export const AUDIO_PATHS: Record<string, string> = {
  rain: '/audio/rain.mp3',
  rain_indoor: '/audio/rain_indoor.mp3',
  storm: '/audio/storm.mp3',
  fog: '/audio/fog.mp3',
  snow: '/audio/snow.mp3',
  ambient_city: '/audio/ambient_city.mp3',
  gunshot: '/audio/gunshot.mp3',
  struggle: '/audio/struggle.mp3',
  yell: '/audio/yell.mp3',
  footsteps: '/audio/footsteps.mp3',
  footsteps_once: '/audio/footsteps.mp3',
  coin_clink: '/audio/coin_clink.mp3',
  page_turn: '/audio/page_turn.mp3',
  item_pickup: '/audio/item_pickup.mp3',
  stash: '/audio/stash.mp3',
  eat: '/audio/eat.mp3',
  repair: '/audio/repair.mp3',
  door: '/audio/door.mp3',
  hide: '/audio/hide.mp3',
  whistle: '/audio/whistle.mp3',
  gong: '/audio/gong.mp3',
  alert: '/audio/alert.mp3',
  success: '/audio/success.mp3',
  discovery: '/audio/discovery.mp3',
  storylet: '/audio/storylet.mp3',
  death: '/audio/death.mp3',
  melee_hit: '/audio/melee_hit.mp3',
  player_hurt: '/audio/player_hurt.mp3',
  item_break: '/audio/item_break.mp3',
  thunder: '/audio/thunder.mp3',
  chest_close: '/audio/chest_close.mp3',
  villager_murmur: '/audio/villager_murmur.mp3',
  temple_bell: '/audio/temple_bell.mp3',
  escape_charge: '/audio/escape_charge.mp3',
  disguise_equip: '/audio/disguise_equip.mp3',
  disguise_remove: '/audio/disguise_remove.mp3'
}

export const resolveAudioPath = (sound: string): string | null => {
  const baseName =  sound.replace(/_start$|_stop$/g, '')
  return AUDIO_PATHS[baseName] || null
}

export const FOOTSTEP_SOUND = 'footsteps'
export const FOOTSTEP_SEQUENCE_COUNT = 3
export const FOOTSTEP_SEQUENCE_INTERVAL_MS = 280

export interface FootstepSequencerOptions {
  count?: number
  intervalMs?: number
  setTimeoutFn?: (fn: () => void, ms: number) => unknown
  clearTimeoutFn?: (handle: unknown) => void
}

export interface FootstepSequencer {
  start(volume: number): void
  cancelAll(): void
}

export function createFootstepSequencer(
  playAttempt: (volume: number) => void,
  options: FootstepSequencerOptions = {},
): FootstepSequencer {
  const count = options.count ?? FOOTSTEP_SEQUENCE_COUNT
  const intervalMs = options.intervalMs ?? FOOTSTEP_SEQUENCE_INTERVAL_MS
  const setTimeoutFn = options.setTimeoutFn ?? ((fn, ms) => setTimeout(fn, ms))
  const clearTimeoutFn = options.clearTimeoutFn ?? ((handle) => clearTimeout(handle as ReturnType<typeof setTimeout>))
  let handles: unknown[] = []

  return {
    start(volume: number) {
      playAttempt(volume)
      for (let attempt = 1; attempt < count; attempt += 1) {
        const handle = setTimeoutFn(() => {
          handles = handles.filter(pending => pending !== handle)
          playAttempt(volume)
        }, attempt * intervalMs)
        handles.push(handle)
      }
    },
    cancelAll() {
      for (const handle of handles) clearTimeoutFn(handle)
      handles = []
    },
  }
}