export interface Entity {
  key: string
  name: string
  model_type: string
  id: number
}

export interface Room {
  id?: number
  key: string
  name: string
  x: number
  y: number
  z: number
  exits?: Record<string, string>
  north?: RoomExit
  south?: RoomExit
  east?: RoomExit
  west?: RoomExit
  up?: RoomExit
  down?: RoomExit
  type?: RoomType
  color?: string
  flags?: string[]
	  district?: string
	  indoors?: boolean
	  hiding_spots?: number
	  nurse_available?: boolean
	  safe?: boolean
	  visited?: boolean
  north_door_state?: DoorState
  south_door_state?: DoorState
  east_door_state?: DoorState
  west_door_state?: DoorState
  cx?: number
  cy?: number
}

export interface RoomExit {
    key: string
    name?: string
}

export type RoomType = 'road' | 'city' | 'indoor' | 'field' | 'mountain' | 'water' | 'shallow' | 'forest' | 'desert' | 'trail' | 'exit'

export type DoorState = 'open' | 'closed' | 'locked'

export interface World {
  id: number
  key: string
  name: string
}

export interface Player {
  id: number
  key: string
  name: string
  health: number
  max_health: number
  hunger: number
  max_hunger: number
  morale: number
  max_morale: number
  mana: number
  max_mana: number
  stamina: number
  max_stamina: number
  experience: number
  level: number
  archetype?: string
  stance?: string
  target?: Entity
}

export interface Character {
  id: number
  key: string
  name: string
  is_player?: boolean
}

export interface Message {
  id: string
  type: string
  text: string
  timestamp: number
  label?: string
}

export interface Effect {
  id: string
  code: string
  name: string
  actor?: Entity
  target?: Entity
  duration?: number
}

export interface MapData {
  [key: string]: Room
}