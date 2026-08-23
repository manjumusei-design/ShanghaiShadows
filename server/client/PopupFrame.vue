<template>
  <div class="popup-overlay">
    <div
      ref="panelEl"
      class="popup-panel"
      :class="{ 'popup-panel--reduce-motion': reducedMotion }"
      :style="panelStyle"
      tabindex="-1"
      @keydown="handleKeydown"
    >
      <div class="popup-header">
        <div class="popup-heading">
          <div class="popup-title">{{ title }}</div>
          <div v-if="meta" class="popup-meta">{{ meta }}</div>
        </div>
        <button v-if="dismissible" type="button" class="popup-close" @click="emit('close')">×</button>
      </div>
      <div class="popup-body">
        <slot />
      </div>
      <div class="popup-footer">{{ legend }}</div>
    </div>
  </div>
</template>

<script lang="ts">
import { computed, defineComponent, onMounted, onUnmounted, ref } from 'vue'

const FOCUSABLE_SELECTOR = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
export default defineComponent({
  name: 'PopupFrame',
  props: {
    title: { type: String, required: true },
    meta: { type: String, default: '' },
    legend: { type: String, default: '↑/↓ move · Enter confirm · Esc close' },
    width: { type: Number, default: 600 },
    height: { type: String, default: '65vh' },
    dismissible: { type: Boolean, default: true },
  },
  emits: ['close'],
  setup(props, { emit }) {
    const panelEl = ref<HTMLElement | null>(null)
    const reducedMotion = ref(
      typeof window !== 'undefined' && window.matchMedia
        ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
        : false
    )

    const panelStyle = computed(() => ({
      width: `min(${props.width}px, calc(100vw - 48px))`,
      height: `min(${props.height}, calc(100vh - 48px))`,
    }))

    const handleWindowKeydown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.preventDefault()
      emit('close')
    }

    onMounted(() => {
      window.addEventListener('keydown', handleWindowKeydown)
    })

    onUnmounted(() => {
      window.removeEventListener('keydown', handleWindowKeydown)
    })

    const handleKeydown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return
      const panel = panelEl.value
      if (!panel) return
      const focusables = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
        .filter((el) => !el.hasAttribute('disabled'))
      if (focusables.length === 0) {
        e.preventDefault()
        return
      }
      e.preventDefault()
      const active = document.activeElement as HTMLElement | null
      const current = panel.contains(active) ? focusables.indexOf(active) : -1
      if (e.shiftKey) {
        const target = current <= 0 ? focusables[focusables.length - 1] : focusables[current - 1]
        target.focus()
      } else {
        const target = current === -1 || current >= focusables.length - 1 ? focusables[0] : focusables[current + 1]
        target.focus()
      }
    }

    return { panelEl, panelStyle, reducedMotion, handleKeydown, emit }
  },
})
</script>

<style lang="scss" scoped>
.popup-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.6);
}

.popup-panel {
  z-index: 10001;
  display: flex;
  flex-direction: column;
  background: #0d0d0d;
  border: 1px solid #1a1a1a;
  border-radius: 4px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  outline: none;
  animation: popup-in 140ms ease-out;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
}

.popup-panel--reduce-motion {
  animation: none;
}

@keyframes popup-in {
  from {
    opacity: 0;
    transform: translateY(6px) scale(0.99);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.popup-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  border-bottom: 1px solid #1a1a1a;
}

.popup-title {
  color: #ffd24a;
  font-size: 16px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.popup-meta {
  color: #999;
  font-size: 11px;
  margin-top: 2px;
}

.popup-close {
  background: transparent;
  border: 1px solid #2a2a2a;
  border-radius: 3px;
  color: #999;
  font-size: 14px;
  line-height: 1;
  padding: 4px 8px;
  cursor: pointer;

  &:hover {
    color: #ffd24a;
    border-color: #ffd24a;
  }
}

.popup-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 20px;
}

.popup-footer {
  padding: 10px 20px;
  border-top: 1px solid #242424;
  color: #777;
  font-size: 12px;
  font-style: italic;
}
</style>
