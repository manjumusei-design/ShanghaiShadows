
export type MessageType =
  | 'room'
  | 'npc'
  | 'ambient'
  | 'discovery'
  | 'social'
  | 'event'
  | 'status'
  | 'system'
  | 'combat'
  | 'tutorial'
  | 'command'
  | 'error'
  | 'success'
  | 'warning'
  | 'weather_rain'
  | 'weather_storm'
  | 'weather_fog'
  | 'weather_snow'
  | 'weather_clear'
  | 'room_exits'
  | 'room_items'
  | 'room_npcs'
  | 'room_tags'
  | 'npc_ambient'
  | 'player_action'
  | 'default'
  | 'unknown'

export interface MessageStyle {
  borderColor: string
  backgroundColor: string
  color: string
  label?: string
}

export const MESSAGE_STYLES: Record<string, MessageStyle> = {
  room: {
    borderColor: '#cccccc',
    backgroundColor: 'transparent',
    color: '#cccccc',
  },
  room_tags: {
    borderColor: 'transparent',
    backgroundColor: 'transparent',
    color: '#888888',
  },
  npc_ambient: {
    borderColor: 'transparent',
    backgroundColor: 'transparent',
    color: '#888888',
  },
  ambient: {
    borderColor: 'transparent',
    backgroundColor: 'transparent',
    color: '#888888',
  },
  room_exits: {
    borderColor: '#44dddd',
    backgroundColor: 'transparent',
    color: '#44dddd',
  },
  discovery: {
    borderColor: '#44dddd',
    backgroundColor: 'transparent',
    color: '#44dddd',
    label: 'Discovery'
  },
  room_items: {
    borderColor: '#ffdd44',
    backgroundColor: 'rgba(255, 221, 68, 0.08)',
    color: '#ffdd44',
    label: 'i'
  },
  tutorial: {
    borderColor: '#ffdd44',
    backgroundColor: 'rgba(255, 221, 68, 0.08)',
    color: '#ffdd44',
    label: 'Hint'
  },
  event: {
    borderColor: '#ffdd44',
    backgroundColor: 'rgba(255, 221, 68, 0.08)',
    color: '#ffdd44',
    label: 'Event'
  },
  room_npcs: {
    borderColor: '#44ff44',
    backgroundColor: 'transparent',
    color: '#44ff44',
    label: '@'
  },
  npc: {
    borderColor: '#44ff44',
    backgroundColor: 'transparent',
    color: '#44ff44',
  },
  social: {
    borderColor: '#44ff44',
    backgroundColor: 'transparent',
    color: '#44ff44',
    label: 'Social'
  },
  status: {
    borderColor: '#8fa8c7',
    backgroundColor: 'transparent',
    color: '#8fa8c7',
    label: 'Status'
  },
  system: {
    borderColor: '#ff44ff',
    backgroundColor: 'rgba(255, 68, 255, 0.08)',
    color: '#ff44ff',
    label: 'System'
  },
  combat: {
    borderColor: '#ff4444',
    backgroundColor: 'rgba(255, 68, 68, 0.10)',
    color: '#ff4444',
    label: '!'
  },
  combat_narration: {
    borderColor: '#ff4444',
    backgroundColor: 'rgba(255, 68, 68, 0.10)',
    color: '#ff4444',
    label: '!'
  },
	  command: {
    borderColor: '#cccccc',
    backgroundColor: 'transparent',
    color: '#cccccc',
  },
  error: {
    borderColor: '#ff4444',
    backgroundColor: 'rgba(255, 68, 68, 0.10)',
    color: '#ff4444',
    label: '!'
  },
  success: {
    borderColor: '#44ff44',
    backgroundColor: 'transparent',
    color: '#44ff44',
    label: 'Status'
  },
  warning: {
    borderColor: '#ffdd44',
    backgroundColor: 'rgba(255, 221, 68, 0.08)',
    color: '#ffdd44',
    label: 'Event'
  },
  weather_rain: {
    borderColor: 'transparent',
    backgroundColor: 'transparent',
    color: '#888888',
  },
  weather_storm: {
    borderColor: 'transparent',
    backgroundColor: 'transparent',
    color: '#888888',
  },
  weather_fog: {
    borderColor: 'transparent',
    backgroundColor: 'transparent',
    color: '#888888',
  },
  weather_snow: {
    borderColor: 'transparent',
    backgroundColor: 'transparent',
    color: '#888888',
  },
  weather_clear: {
    borderColor: 'transparent',
    backgroundColor: 'transparent',
    color: '#888888',
  },
  default: {
    borderColor: 'transparent',
    backgroundColor: 'transparent',
    color: '#cccccc',
    label: ''
  }
}
export const SERVER_TYPE_MAP: Record<string, string> = {
  'room': 'room',
  'look': 'room',
  'exits': 'room_exits',
  'room_description': 'room',
  'room_title': 'room',
  'room_tags': 'room_tags',
  'room_exits': 'room_exits',
  'room_items': 'room_items',
  'room_npcs': 'room_npcs',
  'npc': 'npc',
  'npc_dialogue': 'npc',
  'npc_ambient': 'npc_ambient',
  'talk': 'npc',
  'gossip': 'npc',
  'ambient': 'ambient',
  'atmosphere': 'ambient',
  'sound': 'ambient',
  'internal_monologue': 'ambient',
  'discovery': 'discovery',
  'social': 'social',
  'event': 'event',
  'player_action': 'room',
  'status': 'status',
  'player_status': 'status',
  'system': 'system',
  'info': 'system',
  'help': 'system',
  'prompt': 'system',
  'storylet_frame': 'system',
  'storylet_display': 'system',
  'map_menu': 'system',
  'combat': 'combat',
  'combat_narration': 'combat_narration',
  'attack': 'combat',
  'damage': 'combat',
  'defend': 'combat',
  'death': 'combat',
  'kill': 'combat',
  'hint': 'tutorial',
  'tutorial': 'tutorial',
  'tutorial_npc': 'npc',
  'success': 'success',
  'error': 'error',
  'warning': 'warning',
  'weather_rain': 'weather_rain',
  'weather_storm': 'weather_storm',
  'weather_fog': 'weather_fog',
  'weather_snow': 'weather_snow',
  'weather_clear': 'weather_clear',
  'weather': 'ambient',
  'default': 'default'
}

export function getMessageType(serverType: string | undefined): string {
  if (!serverType) return 'default'
  return SERVER_TYPE_MAP[serverType.toLowerCase()] || 'default'
}

export function getMessageLabel(displayType: string): string {
  const labels: Record<string, string> = {
    npc: '', room_npcs: '@', social: '@',
    room_items: 'i',
    combat: '!', combat_narration: '!', error: '!',
    tutorial: 'Hint', event: 'Event',
    system: 'System', discovery: 'Discovery',
    status: 'Status',
  }
  return labels[displayType] || ''
}

export function getMessageStyle(messageType: string): MessageStyle {
  return MESSAGE_STYLES[messageType] || MESSAGE_STYLES.default
}
