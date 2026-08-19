<template>
  <div class="list-popup">
    <div class="stash-note">{{ payload.retrieval_note }}</div>
    <div ref="listEl" class="list-popup-list" tabindex="0" @keydown="onListKeydown">
      <div
        v-for="(item, idx) in payload.items"
        :key="item.id"
        class="list-row"
        :class="{ 'list-row--active': idx === highlight }"
        @click="highlight = idx"
      >
        <span class="list-row-name">{{ item.name }}</span>
      </div>
      <div v-if="payload.items.length === 0" class="list-empty">Your stash is empty.</div>
    </div>
    <ItemDetailsSection :item="highlightedItem" />
    <div class="list-popup-actions">
      <button type="button" class="popup-action" :disabled="payload.items.length === 0" @click="retrieveAll">Retrieve All</button>
      <button type="button" class="popup-action" @click="emit('close')">Close</button>
    </div>
  </div>
</template>

<script lang="ts">
import { computed, defineComponent, onMounted, ref } from 'vue'
import type { PropType } from 'vue'
import { useStore } from 'vuex'
import ItemDetailsSection from './ItemDetailsSection.vue'
import type { ItemRow, StashPayload } from '../../store/modules/popup'

export default defineComponent({
  name: 'StashPopup',
  components: { ItemDetailsSection },
  props: {
    payload: { type: Object as PropType<StashPayload>, required: true },
  },
  emits: ['close'],
  setup(props, { emit }) {
    const store = useStore()
    const highlight = ref(0)
    const listEl = ref<HTMLElement | null>(null)

    const highlightedItem = computed<ItemRow | null>(() => props.payload.items[highlight.value] || null)

    const retrieveAll = () => {
      if (props.payload.items.length === 0) return
      store.dispatch('popup/sendPopupAction', {
        action: 'retrieve_all',
        room_key: store.state.game.room_key,
      })
    }

    const onListKeydown = (e: KeyboardEvent) => {
      const count = props.payload.items.length
      if (count === 0) return
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        highlight.value = (highlight.value + 1) % count
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        highlight.value = (highlight.value - 1 + count) % count
      } else if (e.key === 'Enter') {
        e.preventDefault()
        retrieveAll()
      }
    }

    onMounted(() => {
      listEl.value?.focus()
    })

    return { highlight, highlightedItem, retrieveAll, onListKeydown, listEl, emit }
  },
})
</script>

<style lang="scss" scoped>
@use '../../styles/popups' as *;

.stash-note {
  color: #b3a078;
  font-size: 12px;
  font-style: italic;
  padding: 9px 12px;
  background: rgba(255, 210, 74, 0.04);
  border: 1px solid #242424;
  border-radius: 4px;
  line-height: 1.5;
}
</style>
