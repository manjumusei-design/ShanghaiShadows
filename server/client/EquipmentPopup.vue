<template>
  <div class="list-popup">
    <div ref="listEl" class="list-popup-list" tabindex="0" @keydown="onListKeydown">
      <template v-for="(section, sIdx) in sections" :key="section.label">
        <div v-if="section.rows.length" class="list-section-label">{{ section.label }}</div>
        <div
          v-for="(row, i) in section.rows"
          :key="section.label + ':' + row.key"
          class="list-row"
          :class="{ 'list-row--active': flatIndex(sIdx, i) === highlight }"
          @click="highlight = flatIndex(sIdx, i)"
        >
          <span class="list-row-name">{{ row.name }}</span>
          <span class="list-row-actions">
            <button type="button" class="row-action" @click="runAction(row)">{{ row.actionLabel }}</button>
          </span>
        </div>
      </template>
      <div v-if="rows.length === 0" class="list-empty">You have no equipment.</div>
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
import { disguiseDisplayName } from '../../core/displayNames'
import type { EquipmentPayload, ItemRow } from '../../store/modules/popup'

interface Row {
  key: string
  name: string
  item: ItemRow | null
  action: string
  actionLabel: string
}

const ACTION_LABELS: Record<string, string> = { equip: 'EQUIP', remove: 'REMOVE' }

export default defineComponent({
  name: 'EquipmentPopup',
  components: { ItemDetailsSection },
  props: {
    payload: { type: Object as PropType<EquipmentPayload>, required: true },
  },
  emits: ['close'],
  setup(props, { emit }) {
    const store = useStore()
    const highlight = ref(0)
    const listEl = ref<HTMLElement | null>(null)

    const disguiseName = computed(() =>
      props.payload.disguise ? disguiseDisplayName(props.payload.disguise, store.state.game.player_disguise) : ''
    )

    const sections = computed(() => {
      const built: { label: string; rows: Row[] }[] = []
      if (props.payload.weapon) {
        built.push({
          label: 'Weapon',
          rows: [{
            key: props.payload.weapon.id,
            name: props.payload.weapon.name,
            item: props.payload.weapon,
            action: 'remove',
            actionLabel: 'REMOVE',
          }],
        })
      }
      if (props.payload.armour) {
        built.push({
          label: 'Armour',
          rows: [{
            key: props.payload.armour.id,
            name: props.payload.armour.name,
            item: props.payload.armour,
            action: 'remove',
            actionLabel: 'REMOVE',
          }],
        })
      }
      if (disguiseName.value) {
        built.push({
          label: 'Disguise',
          rows: [{
            key: 'disguise',
            name: disguiseName.value,
            item: { id: 'disguise', name: disguiseName.value },
            action: 'remove',
            actionLabel: 'REMOVE',
          }],
        })
      }
      const eligible = props.payload.eligible.map((item) => ({
        key: item.id,
        name: item.name,
        item,
        action: 'equip',
        actionLabel: 'EQUIP',
      }))
      if (eligible.length) {
        built.push({ label: 'Eligible Carried Equipment', rows: eligible })
      }
      return built
    })

    const rows = computed(() => sections.value.flatMap((section) => section.rows))

    const flatIndex = (sIdx: number, rowIdx: number) => {
      let offset = 0
      for (let i = 0; i < sIdx; i++) offset += sections.value[i].rows.length
      return offset + rowIdx
    }

    const highlightedItem = computed<ItemRow | null>(() => rows.value[highlight.value]?.item || null)

    const runAction = (row: Row) => {
      if (!row.item) return
      store.dispatch('popup/sendPopupAction', { action: row.action, target_id: row.item.id })
    }

    const onListKeydown = (e: KeyboardEvent) => {
      const count = rows.value.length
      if (count === 0) return
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        highlight.value = (highlight.value + 1) % count
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        highlight.value = (highlight.value - 1 + count) % count
      } else if (e.key === 'Enter') {
        e.preventDefault()
        const row = rows.value[highlight.value]
        if (row) runAction(row)
      }
    }

    onMounted(() => {
      listEl.value?.focus()
    })

    return {
      sections, rows, flatIndex, highlightedItem, runAction, onListKeydown, highlight, disguiseName, listEl, emit,
    }
  },
})
</script>

<style lang="scss" scoped>
@use '../../styles/popups' as *;
</style>
