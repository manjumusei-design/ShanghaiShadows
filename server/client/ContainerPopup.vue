<template>
  <div class="list-popup">
    <div v-if="payload.key_id" class="container-keyline">
      Key: {{ payload.key_name }}{{ payload.has_key ? ' (you have it)' : '' }}
    </div>
    <div ref="listEl" class="list-popup-list" tabindex="0" @keydown="onListKeydown">
      <div
        v-for="(item, idx) in payload.items"
        :key="item.instance_id"
        class="list-row"
        :class="{ 'list-row--active': idx === highlight }"
        @click="highlight = idx"
      >
        <span class="list-row-name">{{ item.name }}</span>
        <span class="list-row-actions">
          <button type="button" class="row-action" @click="take(item)">TAKE</button>
        </span>
      </div>
      <div v-if="payload.items.length === 0" class="list-empty">It is empty.</div>
    </div>
    <ItemDetailsSection :item="highlightedItem" />
    <div class="list-popup-actions">
      <button type="button" class="popup-action" @click="closeContainer">Close</button>
    </div>
  </div>
</template>

<script lang="ts">
import { computed, defineComponent, onMounted, ref } from 'vue'
import type { PropType } from 'vue'
import { useStore } from 'vuex'
import ItemDetailsSection from './ItemDetailsSection.vue'
import type { ContainerItem, ContainerPayload, ItemRow } from '../../store/modules/popup'

export default defineComponent({
  name: 'ContainerPopup',
  components: { ItemDetailsSection },
  props: {
    payload: { type: Object as PropType<ContainerPayload>, required: true },
  },
  emits: ['close'],
  setup(props, { emit }) {
    const store = useStore()
    const highlight = ref(0)
    const listEl = ref<HTMLElement | null>(null)

    const highlightedItem = computed<ItemRow | null>(() => props.payload.items[highlight.value] || null)

    const take = (item: ContainerItem) => {
      store.dispatch('popup/sendPopupAction', {
        action: 'take_from',
        target_id: item.instance_id,
        context_id: props.payload.container_id,
        room_key: store.state.game.room_key,
      })
    }

    const closeContainer = () => {
      store.dispatch('popup/sendPopupAction', {
        action: 'close',
        context_id: props.payload.container_id,
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
        const item = props.payload.items[highlight.value]
        if (item) take(item)
      }
    }

    onMounted(() => {
      listEl.value?.focus()
    })

    return { highlight, highlightedItem, take, closeContainer, onListKeydown, listEl, emit }
  },
})
</script>

<style lang="scss" scoped>
@use '../../styles/popups' as *;

.container-keyline {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #c8c8c8;
  font-size: 12px;
  padding: 9px 12px;
  background: rgba(255, 210, 74, 0.05);
  border: 1px solid #242424;
  border-radius: 4px;

  &::before {
    content: 'KEY';
    color: #8a8a8a;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 1.5px;
  }
}
</style>
