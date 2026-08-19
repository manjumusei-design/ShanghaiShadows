<template>
  <Teleport to="body">
    <PopupFrame
      v-if="active"
      :title="title"
      :meta="meta"
      :width="width"
      :height="height"
      :dismissible="active.kind !== 'container'"
      :legend="legend"
      @close="close"
    >
      <component :is="popupComponent" :payload="active.payload" :context="active.context" @close="close" />
    </PopupFrame>
  </Teleport>
</template>

<script lang="ts">
import { computed, defineComponent, watch } from 'vue'
import { useStore } from 'vuex'
import type { Component } from 'vue'
import PopupFrame from './PopupFrame.vue'
import StorePopup from './StorePopup.vue'
import InventoryPopup from './InventoryPopup.vue'
import EquipmentPopup from './EquipmentPopup.vue'
import ContainerPopup from './ContainerPopup.vue'
import StashPopup from './StashPopup.vue'
import JournalPopup from './JournalPopup.vue'
import ItemActionPopup from './ItemActionPopup.vue'
import { disguiseDisplayName, roomDisplayName } from '../../core/displayNames'
import type { PopupKind } from '../../store/modules/popup'

const POPUP_COMPONENTS: Partial<Record<PopupKind, Component>> = {
  store: StorePopup,
  inventory: InventoryPopup,
  equipment: EquipmentPopup,
  container: ContainerPopup,
  stash: StashPopup,
  journal: JournalPopup,
  action: ItemActionPopup,
}

const KIND_WIDTH: Record<PopupKind, number> = {
  store: 720,
  inventory: 700,
  equipment: 640,
  container: 680,
  stash: 660,
  journal: 880,
  action: 620,
}

const KIND_HEIGHT: Record<PopupKind, string> = {
  store: '65vh',
  inventory: '65vh',
  equipment: '62vh',
  container: '65vh',
  stash: '62vh',
  journal: '70vh',
  action: '60vh',
}

export default defineComponent({
  name: 'PopupHost',
  components: { PopupFrame },
  setup() {
    const store = useStore()
    const active = computed(() => store.state.popup.active as any)

    const title = computed(() => {
      const a = active.value
      if (!a) return ''
      switch (a.kind) {
        case 'store': return a.payload.vendor_name
        case 'inventory': return 'Inventory'
        case 'equipment': return 'Equipment'
        case 'container': return a.payload.name
        case 'stash': return a.payload.safehouse_name
        case 'action': return a.payload.title
        default: return 'Journal'
      }
    })

    const meta = computed(() => {
      const a = active.value
      if (!a) return ''
      const money = store.state.game.player_money || { fabi: 0, silver: 0, military_yen: 0 }
      const roomName = store.state.game.room?.name
      const moneyText = (currency: string) => {
        const key = currency === 'military_yen' ? 'military_yen' : 'fabi'
        const label = currency === 'military_yen' ? 'military yen' : 'fabi'
        return `${money[key] ?? 0} ${label}`
      }
      switch (a.kind) {
        case 'store':
          return `${roomDisplayName(a.payload.room_key, roomName)} · ${moneyText(a.payload.currency)} available`
        case 'inventory':
          return `${a.payload.slots_used} of ${a.payload.slots_max} slots used · ${moneyText('fabi')}`
        case 'equipment': {
          const disguise = disguiseDisplayName(a.payload.disguise, store.state.game.player_disguise)
          return disguise ? `Disguised as ${disguise}` : 'No disguise'
        }
        case 'container': {
          const stateLine = a.payload.locked ? 'Locked' : a.payload.is_open ? 'Open' : 'Closed'
          return `${roomDisplayName(a.payload.room_key, roomName)} · ${stateLine}`
        }
        case 'stash':
          return roomDisplayName(a.payload.room_key, roomName)
        case 'action':
          return roomDisplayName(a.payload.room_key, roomName)
        default:
          return `${store.state.game.game_time} · Day ${store.state.game.day}`
      }
    })

    const width = computed(() => active.value ? KIND_WIDTH[active.value.kind] : 600)
    const height = computed(() => active.value ? KIND_HEIGHT[active.value.kind] : '65vh')
    const popupComponent = computed(() => active.value ? POPUP_COMPONENTS[active.value.kind] : undefined)
    const legend = computed(() => {
      if (active.value && active.value.kind === 'container') {
        return '↑/↓ move · Enter take · Close with the button below'
      }
      return undefined
    })

    const close = () => {
      store.dispatch('popup/closePopup')
    }

    watch(() => store.state.game.room_key, (key) => {
      const a = store.state.popup.active
      if (a && a.context && a.context.room_key !== key) {
        store.dispatch('popup/closePopup')
      }
    })

    return { active, title, meta, width, height, popupComponent, legend, close }
  },
})
</script>
