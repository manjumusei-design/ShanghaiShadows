<template>
  <div class="list-popup store-popup">
    <div class="store-layout">
      <div class="store-list-pane">
        <div class="pane-caption">Available Stock</div>
        <div ref="listEl" class="list-popup-list" tabindex="0" @keydown="onListKeydown">
          <div
            v-for="(item, idx) in payload.items"
            :key="item.id"
            class="list-row"
            :class="{ 'list-row--active': idx === highlight, 'list-row--dim': !canAfford(item) }"
            @click="highlight = idx"
          >
            <span class="list-row-name">{{ item.name }}</span>
            <span class="list-row-price">{{ item.price }} {{ currencyLabel(item.currency) }}</span>
          </div>
        </div>
      </div>
      <div class="store-details-pane">
        <div class="pane-caption">Selected Item</div>
        <ItemDetailsSection :item="highlightedItem" />
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { computed, defineComponent, onMounted, ref } from 'vue'
import type { PropType } from 'vue'
import { useStore } from 'vuex'
import ItemDetailsSection from './ItemDetailsSection.vue'
import type { StoreItem, StorePayload } from '../../store/modules/popup'

const CURRENCY_LABELS: Record<string, string> = { fabi: 'fabi', military_yen: 'military yen' }

export default defineComponent({
  name: 'StorePopup',
  components: { ItemDetailsSection },
  props: {
    payload: { type: Object as PropType<StorePayload>, required: true },
  },
  emits: ['close'],
  setup(props, { emit }) {
    const store = useStore()
    const highlight = ref(0)
    const listEl = ref<HTMLElement | null>(null)

    const canAfford = (item: StoreItem) => item.affordable === true

    const currencyLabel = (currency: string) => CURRENCY_LABELS[currency] || currency

    const highlightedItem = computed(() => props.payload.items[highlight.value] || null)

    const buy = () => {
      const item = highlightedItem.value
      if (!item || !canAfford(item)) return
      store.dispatch('popup/sendPopupAction', {
        action: 'buy',
        target_id: item.id,
        context_id: props.payload.vendor_id,
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
        buy()
      }
    }

    onMounted(() => {
      listEl.value?.focus()
    })

    return { highlight, highlightedItem, canAfford, currencyLabel, onListKeydown, buy, listEl, emit }
  },
})
</script>

<style lang="scss" scoped>
@use '../../styles/popups' as *;

.store-popup {
  flex: 1;
  min-height: 0;
}

.store-layout {
  display: grid;
  grid-template-columns: 42% 58%;
  gap: 18px;
  flex: 1;
  min-height: 0;
}

.store-list-pane {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}

.store-list-pane .list-popup-list {
  flex: 1;
  min-height: 0;
  max-height: none;
}

.store-details-pane {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}

.store-details-pane .item-details {
  flex: 1;
}

@media (max-width: 700px) {
  .store-layout {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }

  .store-list-pane .list-popup-list {
    flex: none;
    max-height: 34vh;
  }
}
</style>
