<template>
  <div class="list-popup">
    <template v-if="payload.stage === 'confirm'">
      <div class="confirm-note">{{ payload.note }}</div>
      <div class="list-popup-actions">
        <button type="button" class="popup-action" @click="confirm">Confirm</button>
        <button type="button" class="popup-action" @click="emit('close')">Cancel</button>
      </div>
    </template>
    <template v-else>
      <div ref="listEl" class="list-popup-list" tabindex="0" @keydown="onListKeydown">
        <div
          v-for="(item, idx) in payload.items"
          :key="item.identity"
          class="list-row"
          :class="{ 'list-row--active': idx === highlight, 'list-row--disabled': item.disabled }"
          @click="choose(item)"
        >
          <span class="list-row-name">
            {{ item.name }}
            <span v-if="item.disabled && item.disabled_reason" class="disabled-reason">{{ item.disabled_reason }}</span>
          </span>
        </div>
      </div>
      <ItemDetailsSection :item="highlightedItem" />
    </template>
  </div>
</template>

<script lang="ts">
import { computed, defineComponent, onMounted, ref } from 'vue'
import type { PropType } from 'vue'
import { useStore } from 'vuex'
import ItemDetailsSection from './ItemDetailsSection.vue'
import type { ActionItem, ActionPayload } from '../../store/modules/popup'

export default defineComponent({
  name: 'ItemActionPopup',
  components: { ItemDetailsSection },
  props: {
    payload: { type: Object as PropType<ActionPayload>, required: true },
  },
  emits: ['close'],
  setup(props, { emit }) {
    const store = useStore()
    const highlight = ref(0)
    const listEl = ref<HTMLElement | null>(null)

    const highlightedItem = computed<ActionItem | null>(() => props.payload.items[highlight.value] || null)

    const choose = (item: ActionItem) => {
      if (item.disabled) return
      store.dispatch('popup/sendPopupAction', {
        action: props.payload.action,
        target_id: item.identity,
        room_key: store.state.game.room_key,
        stage: props.payload.stage,
      })
    }

    const confirm = () => {
      store.dispatch('popup/sendPopupAction', {
        action: props.payload.action,
        target_id: props.payload.confirm_target || '',
        room_key: store.state.game.room_key,
        stage: 'confirm',
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
        if (item) choose(item)
      }
    }

    onMounted(() => {
      listEl.value?.focus()
    })

    return { highlightedItem, choose, confirm, onListKeydown, highlight, listEl, emit }
  },
})
</script>

<style lang="scss" scoped>
@use '../../styles/popups' as *;

.confirm-note {
  color: #c8c8c8;
  font-size: 13px;
  line-height: 1.5;
  padding: 12px 14px;
  background: rgba(255, 210, 74, 0.05);
  border: 1px solid #242424;
  border-radius: 4px;
}
</style>
