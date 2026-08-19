<template>
  <div class="map-view" ref="mapContainer">
    <canvas
      ref="canvas"
      id="map"
      :width="width"
      :height="width"
      @click="onClick"
      @mousedown="onMouseDown"
      @mousemove="onMouseMove"
      @mouseup="onMouseUp"
      @mouseleave="onMouseLeave"
      @wheel="onWheel"
    ></canvas>

    <div
      v-if="tooltipRoom"
      class="map-tooltip"
      :style="{ left: tooltipX + 'px', top: tooltipY + 'px' }"
    >
      <div class="tooltip-name">{{ tooltipRoom.name || tooltipRoom.key }}</div>
	      <div
	        class="tooltip-district"
	        :style="{ color: getDistrictColor(tooltipRoom.district) }"
	      >
	        {{ formatZone(tooltipRoom) }} · {{ formatDistrict(tooltipRoom.district) }}
	      </div>
      <div v-if="tooltipRoom.visited === false" class="tooltip-unvisited">
        Not discovered
      </div>
      <template v-if="tooltipRoom && tooltipRoom.visited !== false">
        <div class="tooltip-exits" v-if="getExitList(tooltipRoom).length">
          <span class="tooltip-label">Exits:</span>
          <span v-for="(exit, dir) in getExitList(tooltipRoom)" :key="dir" class="tooltip-exit-dir">
            {{ dir }}
          </span>
        </div>
        <div class="tooltip-detail-row" v-if="tooltipRoom.npc_count">
          <span>{{ tooltipRoom.npc_count }} NPCs</span>
        </div>
        <div class="tooltip-detail-row" v-if="tooltipRoom.item_count">
          <span>{{ tooltipRoom.item_count }} items</span>
        </div>
        <div class="tooltip-detail-row" v-if="tooltipRoom.safe">
          <span class="tooltip-safe">Safe room</span>
        </div>
      </template>
    </div>

    <div class="planes" v-if="show_planes">
      <div class="arrow-up-wrapper">
        <button
          v-if="center?.up"
          class="plane-arrow plane-arrow-up"
          @click="onClickUp"
        >▲</button>
      </div>
      <div class="plane-icon">═</div>
      <div class="plane-icon">═</div>
      <div class="plane-icon">═</div>
      <div class="arrow-down-wrapper">
        <button
          v-if="center?.down"
          class="plane-arrow plane-arrow-down"
          @click="onClickDown"
        >▼</button>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent, ref, computed, watch, onMounted, PropType } from 'vue'
import MapRenderer, { get_map_width, type RoomData, normalizeMapRooms, type RawMapRoom } from '@/core/map'
import type { Room } from '@/core/interfaces'

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

const ZONE_LABELS: Record<string, string> = {
  "bund": "The Bund",
  "old_city": "Old City",
  "hongkou": "Hongkou",
  "french": "French Concession",
  "nanjing_rd": "Nanjing Road",
  "zhabei": "Zhabei",
  "yangpu": "Yangpu",
  "xujiahui": "Xujiahui",
  "refugee_entry": "Tutorial",
  "orientation": "Tutorial Hub",
}

const DISTRICT_LABELS: Record<string, string> = {
  "bund": "The Bund",
  "commercial": "Commercial District",
  "old_city": "Old City",
  "hongkou": "Hongkou",
  "french": "French Concession",
  "docks": "Huangpu Docks",
  "residential": "Residential Lane",
  "warehouse": "Warehouse District",
  "church": "Church District",
  "school": "School District",
  "ccp_base": "Underground Base",
  "gmd_office": "Intelligence Office",
  "hidden_shanghai": "Hidden Shanghai",
  "refugee_entry": "Refugee Entry",
}

export default defineComponent({
  name: 'Map',
  props: {
    center_key: {
      type: String,
      required: true
    },
    radius: {
      type: Number,
      default: 5
    },
    unit: {
      type: Number,
      default: 8
    },
    map: {
      type: Object as PropType<Record<string, Room>>,
      required: true
    },
    rooms_filter: {
      type: Array as PropType<Room[]>,
      default: () => []
    },
    modified_rooms: {
      type: Array as PropType<Room[]>,
      default: () => []
    },
    display_planes: {
      type: Boolean,
      default: true
    }
  },
  emits: ['clickRoom', 'travelToRoom'],
  setup(props, { emit }) {
    const canvas = ref<HTMLCanvasElement | null>(null)
    const mapContainer = ref<HTMLDivElement | null>(null)
    let mapRenderer: MapRenderer | null = null

    const isPanning = ref(false)
    const lastPanX = ref(0)
    const lastPanY = ref(0)
    const hasDragged = ref(false)

    const tooltipRoom = ref<RoomData | null>(null)
    const tooltipX = ref(0)
    const tooltipY = ref(0)

    const width = computed(() => {
      return get_map_width(props.radius, props.unit)
    })

    const center = computed(() => {
      return props.map[props.center_key]
    })

    const show_planes = computed(() => {
      if (!props.display_planes) return false
      if (!center.value) return false
      return !!(center.value.up || center.value.down)
    })

    const rooms_filter_index = computed(() => {
      const index: Record<string, Room> = {}
      for (const room of props.rooms_filter) {
        index[room.key] = room
      }
      return index
    })

    const has_room_filter = computed(() => {
      return props.rooms_filter && props.rooms_filter.length > 0
    })

    const getDistrictColor = (district?: string): string => {
      return DISTRICT_COLORS[district || ''] || '#65686e'
    }

    const formatDistrict = (district?: string): string => {
      if (!district) return 'Unknown Area'
      return DISTRICT_LABELS[district] || district.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    }

    const formatZone = (room: RoomData): string => {
      const z = (room as any).zone || room.district || ''
      return ZONE_LABELS[z] || formatDistrict(z)
    }

    const getExitList = (room: RoomData) => {
      const exits: Record<string, string> = {}
      for (const dir of ['north', 'south', 'east', 'west', 'up', 'down'] as const) {
        const exit = room[dir]
        if (exit && (exit.key || exit.hidden)) {
          exits[dir] = (exit as any).name || exit.key || dir
        }
      }
      return exits
    }

    const getAllRoomsData = (): Record<string, RoomData> => {
      return normalizeMapRooms(props.map as Record<string, RawMapRoom>, props.modified_rooms as RawMapRoom[])
    }

    const renderMap = () => {
      if (!canvas.value) {
        console.warn('[MAP-DEBUG] renderMap: canvas not mounted yet')
        return
      }

      const room = props.map[props.center_key]
      if (!room) {
        console.warn('[MAP-DEBUG] renderMap: center_key not found in map', {
          center_key: props.center_key,
          mapKeys: Object.keys(props.map).slice(0, 10),
          mapSize: Object.keys(props.map).length
        })
        return
      }

      console.log('[MAP-DEBUG] renderMap: rendering', {
        center_key: props.center_key,
        roomName: room.name,
        totalRooms: Object.keys(props.map).length,
        canvasSize: `${canvas.value.width}x${canvas.value.height}`
      })

      const allRooms = getAllRoomsData()

      mapRenderer = new MapRenderer(allRooms, canvas.value, {
        radius: props.radius,
        width: width.value,
        unit: props.unit,
        in_game: true
      })
      mapRenderer.showView(props.center_key)
    }

    const onMouseUp = () => {
      isPanning.value = false
      window.removeEventListener('mouseup', onMouseUp)
    }

    const onMouseDown = (event: MouseEvent) => {
      isPanning.value = true
      hasDragged.value = false
      lastPanX.value = event.clientX
      lastPanY.value = event.clientY
      window.addEventListener('mouseup', onMouseUp)
    }

    const onMouseMove = (event: MouseEvent) => {
      if (isPanning.value && mapRenderer) {
        const dx = event.clientX - lastPanX.value
        const dy = event.clientY - lastPanY.value

        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
          hasDragged.value = true
        }

        if (hasDragged.value) {
          mapRenderer.pan(dx, dy)
          lastPanX.value = event.clientX
          lastPanY.value = event.clientY
        }
      } else if (!isPanning.value && mapRenderer) {
        const room = mapRenderer.findByCoords({
          x: event.offsetX,
          y: event.offsetY
        })

        if (room && room.silhouette !== true) {
          tooltipRoom.value = room
          tooltipX.value = event.clientX + 15
          tooltipY.value = event.clientY + 15
        } else {
          tooltipRoom.value = null
        }
      }
    }

    const onMouseLeave = () => {
      tooltipRoom.value = null
      isPanning.value = false
    }

    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      if (mapRenderer) {
        const delta = event.deltaY > 0 ? -0.1 : 0.1
        mapRenderer.zoomBy(delta, event.offsetX, event.offsetY)
      }
    }

    const onClick = (event: MouseEvent) => {
      if (hasDragged.value) {
        hasDragged.value = false
        return
      }

      if (!mapRenderer) return

      const room = mapRenderer.findByCoords({
        x: event.offsetX,
        y: event.offsetY
      })

      if (room) {
        if (room.silhouette === true) {
          return
        }
        let room_key = room.key
        if (room.key.includes('-exit-')) {
          room_key = room.key.split('-exit-')[0]
        }

        if (room.visited !== false) {
          emit('travelToRoom', room_key)
        }

        const originalRoom = props.map[room_key]
        if (originalRoom) {
          emit('clickRoom', originalRoom)
        }
      }
    }

    const onClickUp = () => {
      const room = props.map[props.center_key]
      if (room?.up) {
        emit('clickRoom', props.map[room.up.key])
      }
    }

    const onClickDown = () => {
      const room = props.map[props.center_key]
      if (room?.down) {
        emit('clickRoom', props.map[room.down.key])
      }
    }

    watch(() => props.center_key, renderMap)
    watch(() => props.rooms_filter, renderMap, { deep: true })
    watch(() => props.map, renderMap, { deep: true })

    onMounted(renderMap)

    return {
      canvas,
      mapContainer,
      width,
      center,
      show_planes,
      tooltipRoom,
      tooltipX,
      tooltipY,
      getDistrictColor,
      formatDistrict,
      formatZone,
      getExitList,
      onMouseDown,
      onMouseMove,
      onMouseUp,
      onMouseLeave,
      onWheel,
      onClick,
      onClickUp,
      onClickDown
    }
  }
})
</script>

<style lang="scss" scoped>
@import "@/styles/colors.scss";

.map-view {
  position: relative;
  pointer-events: none;

  canvas {
    border: 1px solid #444;
    display: block;
    cursor: grab;
    pointer-events: auto;

    &:active {
      cursor: grabbing;
    }
  }

  .map-tooltip {
    position: fixed;
    background: rgba(25, 26, 28, 0.95);
    border: 1px solid #555;
    padding: 8px 12px;
    border-radius: 4px;
    pointer-events: none;
    z-index: 9999;
    font-size: 12px;
    max-width: 200px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);

    .tooltip-name {
      font-weight: bold;
      color: #fff;
      margin-bottom: 4px;
    }

    .tooltip-district {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .tooltip-unvisited {
      font-size: 10px;
      color: #888;
      font-style: italic;
      margin-top: 4px;
      padding-top: 4px;
      border-top: 1px solid #333;
    }

    .tooltip-exits {
      margin-top: 6px;
      padding-top: 4px;
      border-top: 1px solid #333;
      font-size: 11px;
      color: #aaa;

      .tooltip-label {
        margin-right: 4px;
      }

      .tooltip-exit-dir {
        display: inline-block;
        margin: 1px 2px;
        padding: 1px 4px;
        background: #2a2a2a;
        border-radius: 2px;
        font-size: 10px;
        text-transform: uppercase;
      }
    }

    .tooltip-detail-row {
      margin-top: 4px;
      font-size: 11px;
      color: #aaa;
    }

    .tooltip-safe {
      color: #88cc88;
    }
  }

  .planes {
    border-top: 1px solid #444;
    border-right: 1px solid #444;
    position: absolute;
    bottom: 6px;
    left: 1px;
    padding: 0 10px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    background: rgba(25, 26, 28, 0.7);

    .plane-icon {
      width: 28px;
      height: 8px;
      margin: 1px 0;
      color: $color-text-hex-50;
      text-align: center;
      font-size: 10px;
      line-height: 8px;
    }

    .arrow-up-wrapper,
    .arrow-down-wrapper {
      width: 18px;
      height: 22px;
    }

    .plane-arrow {
      width: 18px;
      height: 22px;
      background: transparent;
      border: none;
      color: $color-text;
      cursor: pointer;
      font-size: 12px;

      &:hover {
        color: $color-primary;
      }

      &.plane-arrow-down {
        transform: rotate(180deg);
      }
    }
  }
}
</style>