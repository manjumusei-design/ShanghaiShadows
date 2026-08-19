<template>
  <div class="list-popup">
    <div ref="listEl" class="list-popup-list" tabindex="0" @keydown="onListKeydown">
      <template v-for="(section, sIdx) in sections" :key="section.label">
        <div v-if="section.items.length" class="list-section-label">{{ section.label }}</div>
        <div
          v-for="(item, i) in section.items"
          :key="item.id"
          class="list-row"
          :class="{ 'list-row--active': flatIndex(sIdx, i) === highlight }"
          @click="highlight = flatIndex(sIdx, i)"
        >
          <span class="list-row-name">
            {{ item.name }}
            <span v-if="item.equipped" class="equipped-tag">{{ equippedLabel(item.equipped) }}</span>
          </span>
          <span class="list-row-actions">
            <button
              v-for="action in item.actions"
              :key="action"
              type="button"
              class="row-action"
              @click="runAction(item, action)"
            >{{ actionLabel(action) }}</button>
          </span>
        </div>
      </template>
      <div v-if="visibleItems.length === 0" class="list-empty">You are carrying nothing.</div>
    </div>
    <ItemDetailsSection :item="highlightedItem" />
    <div class="list-popup-actions">
      <button type="button" class="popup-action" @click="emit('close')">Close</button>
    </div>
  </div>
</template>

<script lang="ts">
import { computed, defineComponent, onMounted, ref } from 'vue'
import type { PropType } from 'vue'
import { useStore } from 'vuex'
import ItemDetailsSection from './ItemDetailsSection.vue'
import type { InventoryItem, InventoryPayload } from '../../store/modules/popup'

const ACTION_LABELS: Record<string, string> = {
  eat: 'EAT', equip: 'EQUIP', wear: 'WEAR', remove: 'REMOVE',
  drop: 'DROP', read: 'READ', examine: 'EXAMINE',
}

const EQUIPPED_LABELS: Record<string, string> = { weapon: 'Equipped', armour: 'Worn', disguise: 'Disguised' }

export default defineComponent({
  name: 'InventoryPopup',
  components: { ItemDetailsSection },
  props: {
    payload: { type: Object as PropType<InventoryPayload>, required: true },
  },
  emits: ['close'],
  setup(props, { emit }) {
    const store = useStore()
    const highlight = ref(0)
    const listEl = ref<HTMLElement | null>(null)

    const equippedRows = computed(() => props.payload.items.filter((item) => !!item.equipped))
    const carriedRows = computed(() => props.payload.items.filter((item) => !item.equipped))
    const sections = computed(() => [
      { label: 'Equipped / Worn', items: equippedRows.value },
      { label: 'Carried', items: carriedRows.value },
    ])
    const visibleItems = computed(() => [...equippedRows.value, ...carriedRows.value])

    const flatIndex = (sIdx: number, rowIdx: number) => {
      let offset = 0
      for (let i = 0; i < sIdx; i++) offset += sections.value[i].items.length
      return offset + rowIdx
    }

    const highlightedItem = computed<InventoryItem | null>(() => visibleItems.value[highlight.value] || null)

    const actionLabel = (action: string) => ACTION_LABELS[action] || action.toUpperCase()
    const equippedLabel = (equipped: string) => EQUIPPED_LABELS[equipped] || 'Equipped'

    const runAction = (item: InventoryItem, action: string) => {
      store.dispatch('popup/sendPopupAction', { action, target_id: item.id })
    }

    const onListKeydown = (e: KeyboardEvent) => {
      const count = visibleItems.value.length
      if (count === 0) return
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        highlight.value = (highlight.value + 1) % count
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        highlight.value = (highlight.value - 1 + count) % count
      } else if (e.key === 'Enter') {
        e.preventDefault()
        const item = visibleItems.value[highlight.value]
        if (item && item.actions.length) {
          runAction(item, item.actions[0])
        }
      }
    }

    onMounted(() => {
      listEl.value?.focus()
    })

    return {
      sections, visibleItems, flatIndex, highlightedItem,
      actionLabel, equippedLabel, runAction, onListKeydown, highlight, listEl, emit,
    }
  },
})
</script>

<style lang="scss" scoped>
@use '../../styles/popups' as *;
</style>
