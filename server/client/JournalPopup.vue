<template>
  <div class="journal-popup">
    <div ref="tabsEl" class="journal-tabs" tabindex="0" @keydown="onTabsKeydown">
      <button
        v-for="(tab, idx) in tabs"
        :key="tab.key"
        type="button"
        class="journal-tab"
        :class="{ 'journal-tab--active': idx === activeTab }"
        @click="activeTab = idx"
      >{{ tab.label }}</button>
    </div>
    <div ref="contentEl" class="journal-content" tabindex="0" @keydown="onContentKeydown">
      <template v-if="isTestimonyTab">
        <template v-if="selectedTestimony">
          <button type="button" class="testimony-back" @click="selectedTestimony = null">Back to Testimonies</button>
          <div class="testimony-detail">
            <div class="journal-line">{{ selectedTestimony.date }} · {{ selectedTestimony.place }}</div>
            <div class="journal-line">{{ selectedTestimony.title }}</div>
            <div class="journal-line">{{ selectedTestimony.writer }} · {{ selectedTestimony.source_badge }}</div>
            <div class="testimony-text">{{ selectedTestimony.text }}</div>
          </div>
        </template>
        <template v-else>
          <button
            v-for="entry in testimonyEntries"
            :key="entry.id"
            type="button"
            class="testimony-entry"
            @click="selectedTestimony = entry"
          >
            <span>{{ entry.date }} · {{ entry.title }}</span>
            <span>{{ entry.place }} · {{ entry.writer }} · {{ entry.source_badge }}</span>
          </button>
          <div v-if="testimonyEntries.length === 0" class="list-empty">Nothing here yet.</div>
        </template>
      </template>
      <template v-else>
        <div v-for="line in activeLines" :key="line.key" class="journal-line">{{ line.text }}</div>
        <div v-if="activeLines.length === 0" class="list-empty">Nothing here yet.</div>
      </template>
    </div>
  </div>
</template>

<script lang="ts">
import { computed, defineComponent, onMounted, ref } from 'vue'
import type { PropType } from 'vue'
import { useStore } from 'vuex'
import { missionDisplayTitle, npcDisplayName } from '../../core/displayNames'
import type { JournalPayload } from '../../store/modules/popup'

interface JournalLine {
  key: string
  text: string
}

const TABS = [
  { key: 'events', label: 'Events' },
  { key: 'rumours', label: 'Street Talk' },
  { key: 'conversations', label: 'Conversations' },
  { key: 'intel', label: 'Intel' },
  { key: 'lessons', label: 'Tutorial Lessons' },
  { key: 'missions', label: 'Active Missions' },
  { key: 'testimonies', label: 'Testimonies' },
]

export default defineComponent({
  name: 'JournalPopup',
  props: {
    payload: { type: Object as PropType<JournalPayload>, required: true },
  },
  setup(props) {
    const store = useStore()
    const activeTab = ref(0)
    const contentEl = ref<HTMLElement | null>(null)
    const tabsEl = ref<HTMLElement | null>(null)
    const selectedTestimony = ref<any | null>(null)

    const eventLines = computed<JournalLine[]>(() =>
      (props.payload.events || []).map((event, idx) => ({
        key: `event-${idx}`,
        text: event.text || String(event),
      }))
    )

    const responseLines = (entries: any[]) =>
      entries.map((entry, idx) => ({
        key: `entry-${idx}`,
        text: entry.npc_response || entry.text || String(entry),
      }))

    const rumourLines = computed<JournalLine[]>(() => responseLines(props.payload.rumours || []))
    const conversationLines = computed<JournalLine[]>(() => responseLines(props.payload.conversations || []))

    const intelLines = computed<JournalLine[]>(() => {
      const rows = props.payload.intel || []
      return rows.map((row, idx) => ({
        key: `intel-${idx}`,
        text: `From ${npcDisplayName(row.npc_id, row.npc_name)}: ${row.label}`,
      }))
    })

    const missionLines = computed<JournalLine[]>(() => {
      const activeMissions = store.state.game.active_missions || []
      return (props.payload.active_missions || []).map((mission, idx) => ({
        key: `mission-${idx}`,
        text: missionDisplayTitle(mission.mission_id || String(mission), activeMissions),
      }))
    })

    const lessonLines = computed<JournalLine[]>(() =>
      Object.entries(props.payload.tutorial_lessons || {})
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([stageKey, text]) => ({
          key: `lesson-${stageKey}`,
          text: text,
        }))
    )

    const testimonyEntries = computed(() => props.payload.testimonies || [])
    const isTestimonyTab = computed(() => TABS[activeTab.value].key === 'testimonies')

    const activeLines = computed(() => {
      switch (TABS[activeTab.value].key) {
        case 'events': return eventLines.value
        case 'rumours': return rumourLines.value
        case 'conversations': return conversationLines.value
        case 'intel': return intelLines.value
        case 'lessons': return lessonLines.value
        case 'testimonies': return []
        default: return missionLines.value
      }
    })

    const onTabsKeydown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') {
        e.preventDefault()
        activeTab.value = (activeTab.value + 1) % TABS.length
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        activeTab.value = (activeTab.value - 1 + TABS.length) % TABS.length
      }
    }

    const onContentKeydown = (e: KeyboardEvent) => {
      const el = contentEl.value
      if (!el) return
      if (isTestimonyTab.value && e.key === 'Escape' && selectedTestimony.value) {
        e.preventDefault()
        selectedTestimony.value = null
        return
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        el.scrollTop += 48
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        el.scrollTop -= 48
      }
    }

    onMounted(() => {
      tabsEl.value?.focus()
    })

    return {
      tabs: TABS,
      activeTab,
      activeLines,
      testimonyEntries,
      isTestimonyTab,
      selectedTestimony,
      contentEl,
      tabsEl,
      onTabsKeydown,
      onContentKeydown,
    }
  },
})
</script>

<style lang="scss" scoped>
@use '../../styles/popups' as *;

.journal-popup {
  display: flex;
  flex-direction: column;
  gap: 14px;
  flex: 1;
  min-height: 0;
}

.journal-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  border-bottom: 1px solid #242424;
  padding-bottom: 10px;
  outline: none;
}

.journal-tab {
  background: transparent;
  border: 1px solid #2c2c2c;
  border-radius: 3px;
  color: #9a9a9a;
  font-size: 11px;
  font-weight: 600;
  padding: 6px 14px;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.5px;

  &:hover {
    color: #ffd24a;
    border-color: #ffd24a;
    background: rgba(255, 210, 74, 0.05);
  }
}

.journal-tab--active {
  background: rgba(255, 210, 74, 0.1);
  border-color: #c9a84c;
  color: #ffd24a;
}

.journal-content {
  border: 1px solid #1e1e1e;
  border-radius: 4px;
  background: #101010;
  max-height: 52vh;
  overflow-y: auto;
  padding: 14px 18px;
  outline: none;
  flex: 1;
  min-height: 0;
}

.journal-line {
  color: #c8c8c8;
  font-size: 12.5px;
  line-height: 1.6;
  padding: 3px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);

  &:last-child {
    border-bottom: none;
  }
}

.testimony-entry,
.testimony-back {
  display: flex;
  width: 100%;
  justify-content: space-between;
  gap: 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 3px;
  background: transparent;
  color: #c8c8c8;
  padding: 8px 10px;
  text-align: left;
  cursor: pointer;
}

.testimony-entry:hover,
.testimony-back:hover {
  border-color: #c9a84c;
  color: #ffd24a;
}

.testimony-entry span:last-child {
  color: #8f8f8f;
  text-align: right;
}

.testimony-detail {
  margin-top: 10px;
}

.testimony-text {
  color: #d8d8d8;
  line-height: 1.7;
  padding: 14px 0;
  white-space: pre-wrap;
}
</style>
