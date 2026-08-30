

const COLORS = {
  white: "#EBEBEB",
  gray: "#A2A2A2",
  green: "#279084",
  black: "#191A1C",
  red: "#c13434",
  primary: "#d77617",
  purple: "#8934c1",
  secondary: "#f5c983",
  pink: "#f583e7",
  exit: "#999"
}
const ZONE_COLORS: Record<string, string> = {
  "bund": "#E8B86D",
  "old_city": "#8B4513",
  "hongkou": "#6B8E23",
  "french": "#9370DB",
  "nanjing_rd": "#C94C4C",
  "zhabei": "#708090",
  "yangpu": "#4682B4",
  "xujiahui": "#F5F5DC",
  "refugee_entry": "#A0522D",
  "orientation": "#A0522D",
}
const DEFAULT_ZONE_COLOR = "#65686e"
const DISTRICT_COLORS: Record<string, string> = {
  "bund": "#E8B86D",
  "commercial": "#C94C4C",
  "old_city": "#8B4513",
  "hongkou": "#6B8E23",
  "french": "#9370DB",
  "docks": "#4682B4",
  "residential": "#D2B48C",
  "warehouse": "#708090",
  "church": "#F5F5DC",
  "school": "#87CEEB",
  "ccp_base": "#8B0000",
  "gmd_office": "#2F4F4F",
  "hidden_shanghai": "#4A4A4A",
  "refugee_entry": "#A0522D",
}
const ROOMCOLORS: Record<string, string> = {
  road: "#9497a1",
  city: "#65686e",
  indoor: "#a48d73",
  field: "#8e9422",
  mountain: "#7a5b3e",
  water: "#4798c4",
  shallow: "#4798c4",
  forest: "#207f45",
  desert: "#bf824d",
  trail: "#5a8b73"
}

const INVERSE_DIRECTIONS: Record<string, string> = {
  north: "south",
  south: "north",
  east: "west",
  west: "east",
  up: "down",
  down: "up"
}


const EPS = 1e-6
const TUTORIAL_GRID_STEP_FACTOR = 3.5

function doorSuppressed(room: RoomData | undefined, dir: string): boolean {
  if (!room) return false
  const state = room[`${dir}_door_state` as keyof RoomData] as string | undefined
  return state === "closed" || state === "locked"
}

export const get_room_index_key = (x: number, y: number, z: number): string => {
  return `${x}:${y}:${z}`
}

export const get_map_width = (radius: number, unit: number): number => {
  const width = 4 * unit + 6 * unit * radius
  return width
}

export const get_map_dimensions = (width: number, unit: number) => {
  const center = 4 * unit
  const non_center = width - center
  const remainder = non_center % (6 * unit)
  const radius = (non_center - remainder) / (6 * unit)
  const inner_width = center + radius * unit * 6
  return {
    width: inner_width,
    radius: radius
  }
}

export interface MapRendererOptions {
  radius?: number
  width?: number
  unit?: number
  in_game?: boolean
  map_mode?: MapMode
}

export type MapMode = 'tutorial' | 'world'

export interface MapPresentationPath {
  key: string
  direction: string
  waypoints: [number, number][]
}

export interface RoomData {
  key: string
  x: number
  y: number
  z: number
  type?: string
  color?: string
  flags?: string[]
  district?: string
  zone?: string
  presentation_slot?: number
  visited?: boolean
  silhouette?: boolean
  name?: string
  north?: { key: string; name?: string; hidden?: boolean; tutorial_route_stub?: boolean }
  south?: { key: string; name?: string; hidden?: boolean; tutorial_route_stub?: boolean }
  east?: { key: string; name?: string; hidden?: boolean; tutorial_route_stub?: boolean }
  west?: { key: string; name?: string; hidden?: boolean; tutorial_route_stub?: boolean }
  up?: { key: string }
  down?: { key: string }
  north_door_state?: string
  south_door_state?: string
  east_door_state?: string
  west_door_state?: string
  cx?: number
  cy?: number
  npc_count?: number
  item_count?: number
  safe?: boolean
  presentation_paths?: MapPresentationPath[]
}

export interface RawMapRoom {
  key?: string
  x?: number
  y?: number
  z?: number
  type?: string
  color?: string
  flags?: string[]
  district?: string
  zone?: string
  presentation_slot?: number
  visited?: boolean
  silhouette?: boolean
  name?: string
  exits?: Record<string, string | { key: string; name?: string; tutorial_route_stub?: boolean }>
  north?: { key: string; name?: string; hidden?: boolean; tutorial_route_stub?: boolean }
  south?: { key: string; name?: string; hidden?: boolean; tutorial_route_stub?: boolean }
  east?: { key: string; name?: string; hidden?: boolean; tutorial_route_stub?: boolean }
  west?: { key: string; name?: string; hidden?: boolean; tutorial_route_stub?: boolean }
  up?: { key: string; name?: string; hidden?: boolean }
  down?: { key: string; name?: string; hidden?: boolean }
  north_door_state?: string
  south_door_state?: string
  east_door_state?: string
  west_door_state?: string
  npc_count?: number
  item_count?: number
  safe?: boolean
  presentation_paths?: MapPresentationPath[]
}

function convertRawExits(exits: Record<string, string | { key: string; name?: string; hidden?: boolean; tutorial_route_stub?: boolean }> | undefined): Record<string, { key: string; name?: string; hidden?: boolean; tutorial_route_stub?: boolean }> {
  if (!exits) return {}
  const result: Record<string, { key: string; name?: string; hidden?: boolean; tutorial_route_stub?: boolean }> = {}
  for (const [dir, value] of Object.entries(exits)) {
    if (typeof value === 'string') {
      result[dir] = { key: value }
    } else if (value && value.key) {
      result[dir] = { key: value.key, name: value.name }
    } else if (value && value.hidden) {
      result[dir] = { key: "", hidden: true }
    } else if (value && value.tutorial_route_stub) {
      result[dir] = { key: "", tutorial_route_stub: true }
    }
  }
  return result
}

export function normalizeMapRooms(
  map: Record<string, RawMapRoom>,
  modified_rooms: RawMapRoom[] = [],
): Record<string, RoomData> {
  const roomsData: Record<string, RoomData> = {}
  for (const roomKey in map) {
    const r = map[roomKey]
    const convertedExits = convertRawExits(r.exits)
    roomsData[roomKey] = {
      key: r.key ?? roomKey,
      x: r.x ?? 0,
      y: r.y ?? 0,
      z: r.z ?? 0,
      type: r.type,
      color: r.color,
      flags: r.flags,
      district: r.district,
      zone: r.zone || r.district,
      presentation_slot: r.presentation_slot,
      visited: r.visited,
      name: r.name,
      silhouette: r.silhouette === true,
      north: convertedExits.north || r.north,
      south: convertedExits.south || r.south,
      east: convertedExits.east || r.east,
      west: convertedExits.west || r.west,
      up: convertedExits.up || r.up,
      down: convertedExits.down || r.down,
      north_door_state: r.north_door_state,
      south_door_state: r.south_door_state,
      east_door_state: r.east_door_state,
      west_door_state: r.west_door_state,
      npc_count: r.npc_count,
      item_count: r.item_count,
      safe: r.safe,
      presentation_paths: r.presentation_paths,
    }
  }
  for (const room of modified_rooms) {
    if (room.key && roomsData[room.key]) {
      roomsData[room.key] = { ...roomsData[room.key], ...room } as RoomData
    }
  }
  return roomsData
}

export default class MapRenderer {
  rooms: Record<string, RoomData>
  canvas: HTMLCanvasElement
  options: MapRendererOptions
  radius: number
  width: number
  unit: number
  last_center_key: string
  renderRooms: Record<string, RoomData>
  ctx: CanvasRenderingContext2D
  in_game: boolean
  map_mode: MapMode
  panX: number = 0
  panY: number = 0
  zoom: number = 1
  gridStep: number

  constructor(rooms: Record<string, RoomData>, canvas: HTMLCanvasElement, options?: MapRendererOptions) {
    this.rooms = rooms
    this.canvas = canvas
    this.options = options || {}
    this.ctx = canvas.getContext("2d")!
    this.radius = this.options.radius || 5
    this.width = this.options.width || 272
    this.unit = this.options.unit || 8
    this.last_center_key = ""
    this.renderRooms = {}
    this.in_game = this.options.in_game || false
    this.map_mode = this.options.map_mode || 'world'
    this.gridStep = 3 * this.unit
  }
  getRoomColor(room: RoomData): string {
    let baseColor = DISTRICT_COLORS[room.district || ''] || ZONE_COLORS[room.zone || ''] || DEFAULT_ZONE_COLOR
    if (room.color) {
      baseColor = room.color
    }
    if (room.silhouette === true) {
      return this.dimColor(baseColor, 0.25)
    }

    return baseColor
  }
  dimColor(hex: string, factor: number): string {
    const r = parseInt(hex.slice(1, 3), 16)
    const g = parseInt(hex.slice(3, 5), 16)
    const b = parseInt(hex.slice(5, 7), 16)
    const dim = (v: number) => Math.floor(v * factor).toString(16).padStart(2, '0')

    return `#${dim(r)}${dim(g)}${dim(b)}`
  }
  pan(dx: number, dy: number): void {
    this.panX += dx
    this.panY += dy
    this.refresh()
  }
  zoomBy(delta: number, centerX: number, centerY: number): void {
    const oldZoom = this.zoom
    this.zoom = Math.max(0.5, Math.min(3, this.zoom + delta))
    const scale = this.zoom / oldZoom
    this.panX = centerX - (centerX - this.panX) * scale
    this.panY = centerY - (centerY - this.panY) * scale
    this.refresh()
  }
  resetView(): void {
    this.panX = 0
    this.panY = 0
    this.zoom = 1
    this.refresh()
  }

  updateRooms(rooms: Record<string, RoomData>): void {
    this.rooms = rooms
    this.refresh()
  }

  recenter(): void {
    this.panX = 0
    this.panY = 0
    this.refresh()
  }

  refresh() {
    this.showView(this.last_center_key)
  }

  private getViewCenter(currentRoom: RoomData): { x: number; y: number } {
    if (this.map_mode !== 'tutorial') {
      return { x: currentRoom.x, y: currentRoom.y }
    }

    const rooms = Object.values(this.rooms)
    if (!rooms.length) {
      return { x: currentRoom.x, y: currentRoom.y }
    }

    const xValues = rooms.map((room) => room.x)
    const yValues = rooms.map((room) => room.y)
    return {
      x: (Math.min(...xValues) + Math.max(...xValues)) / 2,
      y: (Math.min(...yValues) + Math.max(...yValues)) / 2,
    }
  }

  findByCoords(coords: { x: number; y: number }): RoomData | null {
    const worldX = (coords.x - this.panX) / this.zoom
    const worldY = (coords.y - this.panY) / this.zoom

    for (const roomKey in this.renderRooms) {
      const room = this.renderRooms[roomKey]
      if (room.cx !== undefined && room.cy !== undefined) {
        const rx = room.cx
        const ry = room.cy
        const w = this.unit * 2

        if (worldX >= rx && worldX <= rx + w && worldY >= ry && worldY <= ry + w) {
          return room
        }
      }
    }
    return null
  }

  showView(center_key: string) {
    this.renderRooms = {}
    const cRoom = { ...this.rooms[center_key] }
    if (!cRoom.key) {
      return
    }
    const canvasW = this.width
    const canvasH = this.width
    const viewCenter = this.getViewCenter(cRoom)
    this.gridStep = this.map_mode === 'tutorial' ? TUTORIAL_GRID_STEP_FACTOR * this.unit : 3 * this.unit
    for (const rkey in this.rooms) {
      const room = { ...this.rooms[rkey] }
      const offsetX = this.gridStep * (room.x - viewCenter.x)
      const offsetY = this.gridStep * (room.y - viewCenter.y)
      room.cx = canvasW / 2 - this.unit + offsetX
      room.cy = canvasH / 2 - this.unit + offsetY

      this.renderRooms[room.key] = room
    }
    this.ctx.clearRect(0, 0, this.width, this.width)
    this.ctx.save()
    this.ctx.translate(this.panX, this.panY)
    this.ctx.scale(this.zoom, this.zoom)
    for (const room_key in this.renderRooms) {
      this.drawRoomConnections(this.renderRooms[room_key])
    }
    for (const room_key in this.renderRooms) {
      this.drawRoom(this.renderRooms[room_key], center_key)
    }

    this.ctx.restore()
    this.last_center_key = center_key
  }

  drawRoomConnections(room: RoomData) {
    if (this.map_mode === 'tutorial' && room.presentation_paths) {
      for (const path of room.presentation_paths) {
        this.drawPresentationPath(room, path)
      }
      for (const direction of ["north", "east", "south", "west"] as const) {
        const toRoom = room[direction]
        if (toRoom && toRoom.tutorial_route_stub) {
          this.drawTutorialStub(room, direction)
        }
      }
      return
    }
    for (const direction of ["north", "east", "south", "west"] as const) {
      const toRoom = room[direction]
      if (toRoom && toRoom.key) {
        this.drawConnection(room, direction)
      } else if (toRoom && toRoom.tutorial_route_stub) {
        this.drawTutorialStub(room, direction)
      }
    }
  }

  drawPresentationPath(room: RoomData, path: MapPresentationPath) {
    const destination = this.renderRooms[path.key]
    if (!destination || destination.z !== room.z) return

    const sourceX = (room.cx || 0) + this.unit
    const sourceY = (room.cy || 0) + this.unit
    const destinationX = (destination.cx || 0) + this.unit
    const destinationY = (destination.cy || 0) + this.unit
    const points: [number, number][] = [
      [sourceX, sourceY],
      ...path.waypoints.map(([x, y]) => [
        sourceX + this.gridStep * (x - room.x),
        sourceY + this.gridStep * (y - room.y),
      ] as [number, number]),
      [destinationX, destinationY],
    ]

    for (let index = 0; index < points.length - 1; index += 1) {
      const [x1, y1] = points[index]
      const [x2, y2] = points[index + 1]
      if (Math.abs(x1 - x2) > EPS && Math.abs(y1 - y2) > EPS) return
    }

    this.ctx.strokeStyle = COLORS.white
    this.ctx.lineWidth = 2
    this.ctx.beginPath()
    this.ctx.moveTo(...points[0])
    for (const point of points.slice(1)) {
      this.ctx.lineTo(...point)
    }
    this.ctx.stroke()
  }

  drawTutorialStub(room: RoomData, dir: string) {
    const [x, y] = this.getExitCoord(room, dir)
    let tx = x
    let ty = y
    if (dir === "north") {
      ty -= this.unit
    } else if (dir === "south") {
      ty += this.unit
    } else if (dir === "east") {
      tx += this.unit
    } else if (dir === "west") {
      tx -= this.unit
    }
    this.ctx.strokeStyle = COLORS.secondary
    this.ctx.lineWidth = 2
    this.ctx.beginPath()
    this.ctx.moveTo(x, y)
    this.ctx.lineTo(tx, ty)
    this.ctx.stroke()
    let f1x = tx
    let f1y = ty
    let f2x = tx
    let f2y = ty
    if (dir === "east") {
      f1x -= 4
      f1y -= 4
      f2x -= 4
      f2y += 4
    } else if (dir === "west") {
      f1x += 4
      f1y -= 4
      f2x += 4
      f2y += 4
    } else if (dir === "north") {
      f1x -= 4
      f1y += 4
      f2x += 4
      f2y += 4
    } else if (dir === "south") {
      f1x -= 4
      f1y -= 4
      f2x += 4
      f2y -= 4
    }
    this.ctx.beginPath()
    this.ctx.moveTo(tx, ty)
    this.ctx.lineTo(f1x, f1y)
    this.ctx.stroke()
    this.ctx.beginPath()
    this.ctx.moveTo(tx, ty)
    this.ctx.lineTo(f2x, f2y)
    this.ctx.stroke()
  }

  drawRoom(room: RoomData, center_key: string) {
    const roomColor = this.getRoomColor(room)
    const x = room.cx || 0
    const y = room.cy || 0
    const w = this.unit * 2
    const isSelected = room.key === center_key

    if (room.silhouette !== true && room.visited === false) {
      this.ctx.fillStyle = COLORS.black
      this.ctx.fillRect(x, y, w, w)
      this.ctx.strokeStyle = COLORS.white
      this.ctx.lineWidth = 1
      this.ctx.strokeRect(x, y, w, w)
      return
    }

    this.ctx.fillStyle = roomColor

    if (isSelected) {
      this.ctx.fillRect(x - 1, y - 1, w + 2, w + 2)
      if (room.flags && room.flags.length) {
        this.drawRoomTab(x, y, room.flags, true)
      }
      this.ctx.fillStyle = COLORS.black
      this.ctx.fillRect(x + 2, y + 2, w - 4, w - 4)
    } else if (room.type === "exit") {
      if (!this.in_game) {
        this.ctx.strokeStyle = COLORS.white
        this.ctx.beginPath()
        this.ctx.arc(x + w / 2, y + w / 2, w / 3, 0, 2 * Math.PI)
        this.ctx.stroke()
      }
      return
    } else {
      this.ctx.fillRect(x, y, w, w)
      if (room.flags && room.flags.length) {
        this.drawRoomTab(x, y, room.flags, false)
      }
    }
    if (room.up && room.down) {
      this.drawTriangle(x + 8, y + 5, { selected: true })
      this.drawTriangle(x + 8, y + 11, { down: true, selected: true })
    } else if (room.up) {
      this.drawTriangle(x + 8, y + 8, { selected: isSelected })
    } else if (room.down) {
      this.drawTriangle(x + 8, y + 8, { selected: isSelected, down: true })
    }
  }

  drawTriangle(x: number, y: number, options: { selected?: boolean; down?: boolean; size?: number } = {}) {
    const color = options.selected ? COLORS.white : COLORS.black
    const size = options.size || 2

    this.ctx.beginPath()
    this.ctx.fillStyle = color

    if (options.down) {
      this.ctx.moveTo(x - 2 * size, y - size)
      this.ctx.lineTo(x + 2 * size, y - size)
      this.ctx.lineTo(x, y + size)
    } else {
      this.ctx.moveTo(x - 2 * size, y + size)
      this.ctx.lineTo(x + 2 * size, y + size)
      this.ctx.lineTo(x, y - size)
    }

    this.ctx.fill()
  }

  drawConnection(room: RoomData, dir: string) {
    const exitRoomAttrs = room[dir as keyof RoomData] as { key: string } | undefined
    if (!exitRoomAttrs) return
    const sourceBlocked = doorSuppressed(room, dir)

    const exitRoom = this.renderRooms[exitRoomAttrs.key]
    const destinationBlocked = doorSuppressed(exitRoom, INVERSE_DIRECTIONS[dir])
    if (!exitRoom || exitRoom.z !== room.z || (this.map_mode !== 'tutorial' && (sourceBlocked || destinationBlocked))) {
      return
    }

    const [fx, fy] = this.getExitCoord(room, dir)
    const [tx, ty] = this.getExitCoord(exitRoom, INVERSE_DIRECTIONS[dir])
    if (Math.abs(fx - tx) > EPS && Math.abs(fy - ty) > EPS) {
      return
    }
    const blocked = sourceBlocked || destinationBlocked
    this.ctx.strokeStyle = blocked ? COLORS.secondary : COLORS.white
    this.ctx.lineWidth = blocked ? 1 : 2
    this.ctx.beginPath()
    this.ctx.moveTo(fx, fy)
    this.ctx.lineTo(tx, ty)
    this.ctx.stroke()
  }

  drawOneWay(toCoords: [number, number], dir: string) {
    const x = toCoords[0]
    const y = toCoords[1]

    this.ctx.beginPath()
    this.ctx.lineWidth = 2
    this.ctx.strokeStyle = COLORS.white

    this.ctx.moveTo(x, y)
    if (dir === "east") {
      this.ctx.lineTo(x - 4, y - 4)
    } else if (dir === "west") {
      this.ctx.lineTo(x + 4, y - 4)
    } else if (dir === "north") {
      this.ctx.lineTo(x - 4, y - 4)
    } else if (dir === "south") {
      this.ctx.lineTo(x - 4, y + 4)
    }
    this.ctx.stroke()

    this.ctx.beginPath()
    this.ctx.moveTo(x, y)
    if (dir === "east") {
      this.ctx.lineTo(x - 4, y + 4)
    } else if (dir === "west") {
      this.ctx.lineTo(x + 4, y + 4)
    } else if (dir === "north") {
      this.ctx.lineTo(x + 4, y - 4)
    } else if (dir === "south") {
      this.ctx.lineTo(x + 4, y + 4)
    }
    this.ctx.stroke()
  }

  getExitCoord(room: RoomData, dir: string): [number, number] {
    let x = room.cx || 0
    let y = room.cy || 0

    if (dir === "north" || dir === "south") {
      x += this.unit
    }
    if (dir === "east" || dir === "west") {
      y += this.unit
    }
    if (dir === "east") {
      x += this.unit * 2
    }
    if (dir === "south") {
      y += this.unit * 2
    }

    return [x, y]
  }

  drawRoomTab(x: number, y: number, flags: string[], selected: boolean) {
    const selOffset = selected ? 1 : 0
    let color: string | undefined

    for (const flag of flags) {
      if (flag === "fountain") {
        color = ROOMCOLORS.water
        break
      } else if (flag === "smob") {
        color = COLORS.red
        break
      } else if (flag === "trainer") {
        color = COLORS.white
        break
      } else if (flag === "exp") {
        color = COLORS.primary
        break
      } else if (flag === "horse") {
        color = ROOMCOLORS.field
        break
      } else if (flag === "shop") {
        color = COLORS.green
        break
      } else if (flag === "inn") {
        color = COLORS.purple
        break
      } else if (flag === "herb") {
        color = COLORS.secondary
        break
      } else if (flag === "action") {
        color = COLORS.pink
        break
      }
    }

    if (color) {
      this.ctx.beginPath()
      this.ctx.fillStyle = COLORS.black
      this.ctx.moveTo(x - 3 - selOffset + this.unit, y - selOffset)
      this.ctx.lineTo(x + this.unit * 2 + selOffset, y - selOffset)
      this.ctx.lineTo(x + this.unit * 2 + selOffset, y + this.unit + 3 - selOffset)
      this.ctx.fill()

      this.ctx.beginPath()
      this.ctx.fillStyle = color
      this.ctx.moveTo(x - 2.5 - selOffset + this.unit, y - selOffset)
      this.ctx.lineTo(x + this.unit * 2 + selOffset, y - selOffset)
      this.ctx.lineTo(x + this.unit * 2 + selOffset, y + this.unit + 2.5 - selOffset)
      this.ctx.fill()
    }
  }
}
