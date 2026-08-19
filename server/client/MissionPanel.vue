<template>
  <div class="mission-panel">
    <div class="section-label">Active Missions</div>
    <div class="mission-scroll">
      <div
        v-for="mission in missions"
        :key="mission.mission_id"
        class="mission-card"
      >
        <div class="mission-header">
          <span class="mission-faction">{{ getFactionLabel(mission.faction) }}</span>
          <span class="mission-title">{{ mission.title }}</span>
        </div>
        <div class="mission-objectives">
          <div
            v-for="(obj, idx) in mission.objectives"
            :key="idx"
            class="objective-item"
          >
            {{ obj }}
          </div>
        </div>
        <div v-if="mission.progress !== undefined" class="mission-progress">
          Progress: {{ mission.progress.current }}/{{ mission.progress.target }}
        </div>
      </div>
      <div v-if="missions.length === 0" class="empty-state">
        No active missions.
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent, PropType } from 'vue'

interface MissionProgress {
  current: number
  target: number
}

interface ActiveMission {
  mission_id: string
  title: string
  faction?: string
  objectives: string[]
  progress?: MissionProgress
  reward?: number
}

const FACTION_LABELS: Record<string, string> = {
  ccp: 'CCP',
  gmd: 'GMD',
  kempeitai: 'Kempeitai',
  green_gang: 'Green Gang',
  french: 'French',
  civilian: 'Civilian',
  resistance: 'Resistance'
}

export default defineComponent({
  name: 'MissionPanel',
  props: {
    missions: {
      type: Array as PropType<ActiveMission[]>,
      required: true
    }
  },
  setup() {
    const getFactionLabel = (faction: string | undefined): string => {
      if (!faction) return 'Mission'
      const baseFaction = faction.split('.')[0]
      return FACTION_LABELS[baseFaction] || faction
    }

    return {
      getFactionLabel
    }
  }
})
</script>

<style scoped lang="scss">
.mission-panel {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.section-label {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #888;
  border-bottom: 1px solid #333;
  padding-bottom: 0.25rem;
}

.mission-scroll {
  max-height: 200px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.mission-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid #444;
  border-radius: 4px;
  padding: 0.5rem;
}

.mission-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}

.mission-faction {
  font-size: 0.65rem;
  text-transform: uppercase;
  background: #333;
  padding: 0.15rem 0.35rem;
  border-radius: 2px;
  color: #aaa;
}

.mission-title {
  font-size: 0.85rem;
  font-weight: 500;
  color: #ddd;
}

.mission-objectives {
  font-size: 0.75rem;
  color: #999;
  margin-bottom: 0.25rem;
}

.objective-item {
  padding-left: 0.75rem;
  position: relative;

  &::before {
    content: '○';
    position: absolute;
    left: 0;
    color: #666;
  }
}

.mission-progress {
  font-size: 0.7rem;
  color: #666;
  border-top: 1px solid #333;
  padding-top: 0.25rem;
  margin-top: 0.25rem;
}

.empty-state {
  font-size: 0.8rem;
  color: #666;
  font-style: italic;
  text-align: center;
  padding: 1rem;
}
</style>
