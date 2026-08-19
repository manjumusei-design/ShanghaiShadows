<template>
  <div
    v-if="warning"
    class="patrol-warning patrol-bar"
    :class="`stage-${warning.stage}`"
    role="status"
    aria-live="polite"
  >
    <span class="patrol-warning-text">{{ stageMessage }}</span>
    <span v-if="countdown !== null" class="patrol-warning-countdown" data-testid="patrol-countdown">
      Movement in {{ countdown }}s
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import type { PropType } from 'vue'
import type { PatrolWarningState } from '@/store/modules/game'

const props = defineProps({
  warning: {
    type: Object as PropType<PatrolWarningState | null>,
    default: null,
  },
})

const now = ref(Date.now())
let timer: number | null = null

onMounted(() => {
  timer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  if (timer !== null) window.clearInterval(timer)
})

const stageMessage = computed(() => {
  switch (props.warning?.stage) {
    case 1:
      return 'Patrol movement is three outdoor route steps away.'
    case 2:
      return 'Patrol movement is two outdoor route steps away.'
    case 3:
      return 'Patrol can reach this room on its next move.'
    default:
      return 'Patrol warning.'
  }
})

const countdown = computed(() => {
  const warning = props.warning
  if (!warning || warning.stage !== 3 || warning.expires_at === undefined) return null
  return Math.max(0, Math.ceil(warning.expires_at - now.value / 1000))
})
</script>

<style scoped>
.patrol-bar {
  margin-top: 6px;
  padding: 4px 10px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  text-align: center;
  letter-spacing: 0.3px;
  transition: background 0.5s ease, color 0.5s ease;
}

.patrol-bar.stage-1 {
  background: rgba(128, 128, 128, 0.2);
  color: #aaaaaa;
  border: 1px solid rgba(128, 128, 128, 0.3);
}

.patrol-bar.stage-2 {
  background: rgba(255, 200, 50, 0.15);
  color: #ffcc33;
  border: 1px solid rgba(255, 200, 50, 0.3);
}

.patrol-bar.stage-3 {
  background: rgba(255, 50, 50, 0.2);
  color: #ff4444;
  border: 1px solid rgba(255, 50, 50, 0.4);
  animation: patrol-pulse 1s ease-in-out infinite;
}

.patrol-warning-countdown {
  display: block;
  margin-top: 2px;
}

@keyframes patrol-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
</style>
