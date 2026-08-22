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
  escape_charge: '/audio/escape_charge.mp3'
}

export const resolveAudioPath = (sound: string): string | null => {
  const baseName =  sound.replace(/_start$|_stop$/g, '')
  return AUDIO_PATHS[baseName] || null
}