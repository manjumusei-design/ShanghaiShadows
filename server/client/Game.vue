<template>
  <div class="game-container">
    <div class="left-panel">
      <div class="char-header">
        <div class="char-name">{{ userName || 'Adventurer' }}</div>
        <div class="char-meta">
          <span class="char-tag">Day {{ day || 1 }}</span>
          <span class="char-tag" v-if="playerDisguise">{{ playerDisguise }}</span>
          <span v-if="wantedLevel > 0" class="char-tag wanted-tag">Wanted {{ wantedLevel }}</span>
          <span v-if="hidden" class="char-tag hidden-tag">Hidden</span>
        </div>
        <div class="char-progress-bar">
          <div class="char-progress-fill" :style="{ width: progressPercent + '%' }"></div>
        </div>
      </div>
      <div class="map-section">
        <div class="section-label">Area Map</div>
        <div class="map-wrapper">
          <Map
            v-if="roomKey && Object.keys(mapData).length > 0"
            :center_key="roomKey"
            :radius="5"
            :unit="8"
            :map="mapData"
            :map_mode="mapMode"
            @travelToRoom="handleTravelToRoom"
          />
        </div>
      </div>
      <div class="tabbed-content">
        <div class="tab-nav">
          <button class="tab-btn" :class="{ active: activeTab === 'vitals' }" @click="activeTab = 'vitals'">Vitals</button>
          <button class="tab-btn" :class="{ active: activeTab === 'inventory' }" @click="activeTab = 'inventory'">Inventory</button>
          <button class="tab-btn" :class="{ active: activeTab === 'stats' }" @click="activeTab = 'stats'">Stats</button>
        </div>
        <div class="tab-content" v-show="activeTab === 'vitals'">
          <div class="vital-row">
            <span class="vital-label">Health</span>
            <div class="vital-bar">
              <div class="vital-fill health" :style="{ width: healthPercent + '%' }"></div>
            </div>
            <span class="vital-value">{{ Math.round(player?.health || 0) }}/{{ player?.max_health || 100 }}</span>
          </div>

          <div class="vital-row">
            <span class="vital-label">Hunger</span>
            <div class="vital-bar">
              <div class="vital-fill hunger" :style="{ width: hungerPercent + '%' }"></div>
            </div>
            <span class="vital-value">{{ Math.round(player?.hunger || 0) }}/{{ player?.max_hunger || 100 }}</span>
          </div>

          <div class="vital-row">
            <span class="vital-label">Morale</span>
            <div class="vital-bar">
              <div class="vital-fill morale" :style="{ width: moralePercent + '%' }"></div>
            </div>
            <span class="vital-value">{{ Math.round(player?.morale || 0) }}/{{ player?.max_morale || 100 }}</span>
          </div>

          <div class="currency-section">
        <div class="currency-row">
          <span class="currency-label">Spendable Fabi</span>
          <span class="currency-value">{{ playerWalletFabiValue }}</span>
        </div>
        <div class="currency-row">
          <span class="currency-label">Silver</span>
          <span class="currency-value">{{ playerMoney.silver }}</span>
        </div>
            <div class="currency-row">
              <span class="currency-label">Mil. Yen</span>
              <span class="currency-value">{{ playerMoney.military_yen }}</span>
            </div>
          </div>
        </div>
        <div class="tab-content" v-show="activeTab === 'inventory'">
          <ul class="inventory-list">
            <li
              v-for="(item, index) in inventory"
              :key="index"
              class="inventory-item"
              @click="item && sendCommand('examine ' + item.name)"
            >
              {{ item.name }}
            </li>
            <li v-if="inventory.length === 0" class="empty-state">No items.</li>
          </ul>
        </div>
        <div class="tab-content" v-show="activeTab === 'stats'">
          <div class="stats-group">
            <div class="stat-row">
              <span class="stat-label">Courage</span>
              <span class="stat-value">{{ playerSkills.courage || 0 }}</span>
            </div>
            <div class="stat-row">
              <span class="stat-label">Perception</span>
              <span class="stat-value">{{ playerSkills.perception || 0 }}</span>
            </div>
            <div class="stat-row">
              <span class="stat-label">Stealth</span>
              <span class="stat-value">{{ playerSkills.stealth || 0 }}</span>
            </div>
          </div>

          <div class="faction-section">
            <div class="section-sublabel">Faction Trust</div>
            <div class="faction-row">
              <span class="faction-name">CCP</span>
              <span class="faction-value">{{ playerTrust.ccp || 50 }}</span>
            </div>
            <div class="faction-row">
              <span class="faction-name">GMD</span>
              <span class="faction-value">{{ playerTrust.gmd || 50 }}</span>
            </div>
            <div class="faction-row">
              <span class="faction-name">Green Gang</span>
              <span class="faction-value">{{ playerTrust.gang || 50 }}</span>
            </div>
            <div class="faction-row">
              <span class="faction-name">Kempeitai</span>
              <span class="faction-value">{{ playerTrust.kempeitai || 50 }}</span>
            </div>
            <div class="faction-row">
              <span class="faction-name">French</span>
              <span class="faction-value">{{ playerTrust.french || 50 }}</span>
            </div>
          </div>
          <div class="influence-section">
            <div class="section-sublabel">Faction Influence</div>
            <div class="influence-row">
              <span class="influence-label">CCP</span>
              <div class="influence-bar">
                <div class="influence-fill ccp" :style="{ width: Math.min(ccpInfluence, 100) + '%' }"></div>
              </div>
              <span class="influence-value">{{ ccpInfluence }}%</span>
            </div>
            <div class="influence-row">
              <span class="influence-label">GMD</span>
              <div class="influence-bar">
                <div class="influence-fill gmd" :style="{ width: Math.min(gmdInfluence, 100) + '%' }"></div>
              </div>
              <span class="influence-value">{{ gmdInfluence }}%</span>
            </div>
          </div>

        </div>
      </div>
      <div class="storylets-section" v-if="activeStorylets.length > 0">
        <div class="section-label">Storylets</div>
        <div class="storylet-list">
          <div v-for="storylet in activeStorylets" :key="storylet.storylet_id" class="storylet-card" :class="{ 'timer-warning': isStoryletUrgent(storylet) }">
            <div class="storylet-title">Event</div>
            <div v-if="storylet.narrative" class="storylet-desc">{{ storylet.narrative }}</div>
            <div v-if="storylet.turns && storylet.turns.length" class="storylet-turns">
              <div v-for="(turn, turnIdx) in storylet.turns" :key="turnIdx" class="storylet-turn">
                <span class="storylet-turn-speaker">{{ turn.speaker }}:</span>
                <span class="storylet-turn-text"> "{{ turn.text }}"</span>
              </div>
            </div>
            <div v-if="storylet.read_only" class="storylet-observer">Another player is deciding how to respond.</div>
            <div class="storylet-timer" v-if="storylet.timer_duration > 0">
              <span class="timer-label">Time remaining: </span>
              <span class="timer-value">{{ formatTimer(storylet) }}</span>
            </div>
            <div class="storylet-options">
              <button
                v-for="(option, idx) in storylet.options"
                :key="idx"
                class="storylet-option"
                :disabled="option.disabled || storylet.read_only || isStoryletExpired(storylet)"
                :title="option.disabled_reason || (isStoryletExpired(storylet) ? 'The moment passes.' : '')"
                @click="sendCommand(String(idx + 1))"
              >
                {{ option.text }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div class="center-panel">
      <div class="location-header">
        <div class="location-name">
          {{ currentRoom?.name || 'Unknown Location' }}
          <span v-if="currentRoom?.safe" class="safe-room-badge">SAFE</span>
        </div>
        <div class="location-meta">
          <span>{{ gameTime }}</span>
          <span>Day {{ day }}</span>
          <span class="weather-info">{{ weather }} Â· {{ season }}</span>
          <span v-if="curfewActive" class="curfew-badge">CURFEW</span>
        </div>
        <PatrolWarning :warning="patrolWarning" />
      </div>
      <div v-if="connectionError" class="connection-error">
        {{ connectionError }}
        <button @click="reconnect" class="reconnect-btn">Reconnect</button>
      </div>
      <div class="terminal" ref="terminalEl" @click="inputEl?.focus()" @scroll="handleTerminalScroll">
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="message-block"
          :class="{ 'message-gated': isGated(msg) }"
          :data-type="msg.type"
          :style="getMessageStyle(msg.type)"
        >
          <span v-if="msg.label" class="msg-label">[{{ msg.label }}]&nbsp;</span>
          <TerminalMessage
            :ref="(el) => registerTerminalMessage(msg.id, el)"
            :text="msg.text"
            :type="msg.type"
            :instant-text="msg.instant_reveal === true"
            :gated="isGated(msg)"
            :previously-revealed="hasSeenReveal(msg.id)"
            @reveal-state="setRevealState(msg.id, $event)"
            @reveal-progress="handleRevealProgress"
            @reveal-complete="handleRevealComplete(msg.id)"
          />
        </div>
      </div>
      <button v-if="hasUnreadOutput" class="unread-jump" @click.stop="jumpToBottom">
        New output ↓
      </button>
      <audio ref="ambientAudioEl"></audio>
      <audio ref="effectsAudioEl"></audio>
      <audio ref="footstepAudioEl"></audio>
      <div class="input-bar">
        <span class="prompt">{{ promptText }}</span>
        <input
          ref="inputEl"
          v-model="inputText"
          @keydown="handleInputKeydown"
          type="text"
          class="command-input"
          placeholder="Enter command..."
          autocomplete="off"
          :disabled="!isConnected"
        />
        <div v-if="filteredSuggestions.length > 0" ref="completionListEl" class="completions-dropdown">
          <div
            v-for="(comp, idx) in filteredSuggestions"
            :key="idx"
            class="completion-option"
            :class="{ active: idx === activeSuggestionIndex }"
            @click="insertCompletion(comp)"
            @mouseenter="activeSuggestionIndex = idx"
          >
            <span class="comp-text">{{ comp }}</span>
            <span class="comp-cat">{{ currentCategory }}</span>
          </div>
        </div>
        <div v-if="showNoMatches && filteredSuggestions.length === 0" class="completions-empty">No matches.</div>
      </div>
    </div>
    <div class="right-panel">
      <div class="room-info-section">
        <div class="section-label">Room Info</div>
        <div class="room-info-card">
          <div class="room-info-zone" v-if="currentRoom?.district">
            {{ getZoneLabel(currentRoom.district) }}
          </div>
          <div class="room-info-types" v-if="roomTags.length">
            <span v-for="tag in roomTags" :key="tag" class="room-type-badge">
              {{ getTagLabel(tag) }}
            </span>
          </div>
          <div class="room-info-badges">
            <span v-if="currentRoom?.indoors === true" class="info-badge indoors-badge"
              :title="'Weather sounds are quieter indoors. Rain is muffled, storms are distant. Hiding is easier indoors.'">
              Indoors
            </span>
            <span v-else-if="currentRoom?.indoors === false" class="info-badge outdoors-badge"
              :title="'Open air. Weather affects this area. Patrols have full visibility during the day.'">
              Outdoors
            </span>
            <span v-if="currentRoom?.safe" class="info-badge safe-badge"
              :title="'Kempeitai patrols cannot enter. You can CLAIM this room as a safehouse.'">
              Safe
            </span>
            <span v-if="currentRoom?.hiding_spots" class="info-badge hiding-badge"
              :title="'Number of places to HIDE. More spots = easier to avoid detection.'">
              Hide {{ currentRoom.hiding_spots }}
            </span>
            <span v-if="currentRoom?.nurse_available" class="info-badge nurse-badge"
              :title="'Medical treatment available here. Restores health.'">
              Nurse
            </span>
          </div>
          <div v-if="!currentRoom" class="empty-state">No info available.</div>
        </div>
      </div>
      <div class="npcs-section">
        <div class="section-label">NPCs Present</div>
        <div class="npc-list">
          <div
            v-for="npc in npcsInRoom"
            :key="npc.id"
            class="npc-card"
          >
            <div class="npc-header">
              <span class="npc-name">{{ npc.name }}</span>
              <span class="npc-faction">{{ npc.faction }}</span>
            </div>
            <div class="npc-standing">{{ npc.standing || 'neutral' }}</div>
          </div>
          <div v-if="npcsInRoom.length === 0" class="empty-state">No NPCs present.</div>
        </div>
      </div>
      <div class="items-section">
        <div class="section-label">Items Here</div>
        <div class="item-list">
          <button
            v-for="(item, index) in itemsInRoom"
            :key="index"
            class="item-btn"
            @click="sendCommand('take ' + item.name)"
          >
            {{ item.name }}
          </button>
          <div v-if="itemsInRoom.length === 0" class="empty-state">No items visible.</div>
        </div>
      </div>
      <MissionPanel :missions="activeMissions" />
      <div class="rumours-panel">
        <div class="section-label">Rumours</div>
        <div class="rumour-scroll">
          <div class="rumour-section">
            <div class="rumour-section-heading">Overheard Exchanges</div>
            <div v-if="typewriterRumours.length === 0" class="empty-state">No overheard exchanges.</div>
            <div v-for="rumour in typewriterRumours" :key="rumour.id" class="rumour-entry" :class="['rumour-type-' + (rumour.type || 'gossip'), { 'rumour-focused': focusedRumourId === rumour.id }]" @click="focusRumour(rumour)">
              <div v-if="rumour.type === 'defection'" class="rumour-defection-header">City News</div>
              <div v-if="rumour.type === 'extortion' || rumour.type === 'intimidation'" class="rumour-warning-marker">Warning</div>
              <div class="rumour-dialogue">
                <div
                  v-for="(turn, li) in rumour.turns"
                  :key="li"
                  class="rumour-dialogue-line"
                  :class="[
                    'turn-' + speakerSide(rumour, turn.speaker),
                    { 'line-revealed': li < rumour.revealedCount, 'line-hidden': li >= rumour.revealedCount, 'turn-active': rumour.activeTurnIndex === li },
                  ]"
                >
                    <div class="rumour-message" :class="{ 'rumour-enter-ltr': li < rumour.revealedCount }">
                    <div v-if="turn.speaker" class="rumour-speaker-name">{{ turn.speaker }}</div>
                    <div class="rumour-bubble">
                      <span v-if="rumour.type === 'shuttering'" class="rumour-shutter-prefix">Shop Closed: </span>
                      <span class="rumour-line">{{ rumour.revealedText[li] }}</span>
                      <span v-if="rumour.activeTurnIndex === li" class="rumour-cursor" aria-hidden="true"></span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="endingData" class="ending-overlay">
      <div class="ending-box">
        <h2>Victory</h2>
        <p class="ending-text">{{ endingData }}</p>
        <button class="form-submit" @click="clearEnding">Continue</button>
      </div>
    </div>
    <div v-if="serverResetNotification" class="server-reset-banner">
      {{ serverResetNotification }}
    </div>
    <PopupHost />
  </div>
</template>

<script lang="ts">
import { defineComponent, ref, computed, onMounted, onUnmounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useStore } from 'vuex'
import { useRouter } from 'vue-router'
import Map from '@/components/Map.vue'
import MissionPanel from '@/components/MissionPanel.vue'
import PopupHost from '@/components/popup/PopupHost.vue'
import PatrolWarning from '@/components/PatrolWarning.vue'
import { getMessageStyle } from '@/core/messageTypes'
import { isRevealed, markRevealed } from '@/core/revealLedger'
import { instantTextPreference, prefersReducedMotion, resolvesToInstantReveal } from '@/core/revealRules'
import { CompletionsEngine } from '@/core/completions'
import { HintScheduler } from '@/core/hintScheduler'
import { createOverheardScheduler } from '@/core/overheardScheduler'
import { FOOTSTEP_SOUND, createFootstepSequencer, resolveAudioPath } from '@/core/audio'
import { visibleRoomTags } from '@/core/roomTags'
import { WeatherEffects } from '@/core/weatherEffects'
import TerminalMessage from '@/components/TerminalMessage.vue'

export default defineComponent({
  name: 'Game',
  components: {
    Map,
    MissionPanel,
    PopupHost,
    PatrolWarning,
    TerminalMessage,
  },
  setup() {
    const store = useStore()
    const router = useRouter()
    const terminalEl = ref<HTMLElement | null>(null)
    const inputEl = ref<HTMLInputElement | null>(null)
    const inputText = ref('')
    let commandInFlight = false
    const autoFollow = ref(true)
    const hasUnreadOutput = ref(false)
    const isNearBottom = (): boolean => {
      const el = terminalEl.value
      if (!el) return true
      return el.scrollHeight - el.scrollTop - el.clientHeight < 60
    }
    const handleTerminalScroll = () => {
      autoFollow.value = isNearBottom()
      if (autoFollow.value) hasUnreadOutput.value = false
    }
    const followOutput = () => {
      const el = terminalEl.value
      if (!el) return
      if (autoFollow.value) {
        el.scrollTop = el.scrollHeight
      } else {
        hasUnreadOutput.value = true
      }
    }
    const jumpToBottom = () => {
      autoFollow.value = true
      hasUnreadOutput.value = false
      const el = terminalEl.value
      if (el) el.scrollTop = el.scrollHeight
    }
    type TerminalMessageRef = { skipReveal: () => void }
    const terminalMessageRefs = new globalThis.Map<string, TerminalMessageRef>()
    const activeRevealIds = ref<string[]>([])
    const registerTerminalMessage = (id: string, instance: TerminalMessageRef | null) => {
      if (instance) {
        terminalMessageRefs.set(id, instance)
      } else {
        terminalMessageRefs.delete(id)
        activeRevealIds.value = activeRevealIds.value.filter(activeId => activeId !== id)
      }
    }
    const setRevealState = (id: string, active: boolean) => {
      if (active) {
        activeRevealIds.value = [...activeRevealIds.value.filter(activeId => activeId !== id), id]
      } else {
        activeRevealIds.value = activeRevealIds.value.filter(activeId => activeId !== id)
      }
    }
    const skipCurrentReveal = (): boolean => {
      const id = activeRevealIds.value[activeRevealIds.value.length - 1]
      if (!id) return false
      const message = terminalMessageRefs.get(id)
      if (!message) return false
      message.skipReveal()
      return true
    }
    const handleRevealProgress = () => {
      nextTick(followOutput)
    }
    const commandHistory = ref<string[]>([])
    const historyIndex = ref(-1)
    const activeTab = ref('vitals')
    const showCompletions = ref(false)
    const compEngine = new CompletionsEngine()
    const filteredSuggestions = ref<string[]>([])
    const activeSuggestionIndex = ref(-1)
    const currentCategory = ref('')
    const showNoMatches = ref(false)
    const completionListEl = ref<HTMLElement | null>(null)

    const pendingDeferredHint = ref<{ hint_id: string; payload: string } | null>(null)
    const displayHint = (hint: { hint_id: string; payload: string }) => {
      store.state.game.messages.push({
        id: 'hint_' + hint.hint_id,
        type: 'tutorial',
        text: hint.payload,
        timestamp: Date.now(),
        label: 'Hint',
      })
      hintScheduler.markShown(hint.hint_id)
    }
    const _showHint = (hint: { hint_id: string; payload: string }) => {
      if (activeRevealIds.value.length > 0) {
        pendingDeferredHint.value = hint
        return
      }
      displayHint(hint)
    }
    watch(activeRevealIds, (ids) => {
      if (ids.length === 0 && pendingDeferredHint.value) {
        const hint = pendingDeferredHint.value
        pendingDeferredHint.value = null
        nextTick(() => displayHint(hint))
      }
    })
    const hintScheduler = new HintScheduler({ onShow: _showHint })
    watch(
      () => store.state.game.tutorial_hint,
      (hint) => {
        if (hint) {
          if (hint.immediate) {
            _showHint(hint)
          } else {
            hintScheduler.enqueue(hint)
          }
        } else {
          hintScheduler.clear()
          pendingDeferredHint.value = null
        }
      }
    )
    watch(
      () => store.state.game.room_key,
      (newRoom, oldRoom) => {
        if (newRoom && oldRoom !== newRoom) {
          hintScheduler.onRoomChange(newRoom)
        }
      }
    )
    onBeforeUnmount(() => hintScheduler.clear())

    const weatherFx = new WeatherEffects()
    const visualsEnabled = ref(localStorage.getItem('ss_visuals_off') !== 'true')
    const weather = computed(() => store.state.game.weather || 'clear')
    watch(weather, (val) => {
      if (visualsEnabled.value) {
        weatherFx.setWeather(val)
      } else {
        weatherFx.setWeather('clear')
      }
    }, { immediate: true })
    onMounted(() => {
      const el = document.getElementById('game-app') || document.body
      weatherFx.mount(el)
    })
    onUnmounted(() => {
      weatherFx.destroy()
    })
    const player = computed(() => store.state.game.player)
    const messages = computed(() => store.state.game.messages)
    const completedRevealIds = ref<Set<string>>(new Set(
      messages.value.filter(msg => isRevealed(msg.id)).map(msg => msg.id)
    ))
    const gatedMessageIds = computed(() => {
      const gated = new Set<string>()
      let frontierPassed = false
      for (const msg of messages.value) {
        if (!frontierPassed) {
          if (completedRevealIds.value.has(msg.id)) continue
          if (resolvesToInstantReveal(msg.type) || msg.instant_reveal === true) continue
          frontierPassed = true
          continue
        }
        if (msg.instant_reveal === true) continue
        gated.add(msg.id)
      }
      return gated
    })
    const isGated = (msg: { id: string }) => gatedMessageIds.value.has(msg.id)
    const hasSeenReveal = (id: string) => isRevealed(id)
    let pendingCompleteIds: string[] | null = null
    let completionFlushScheduled = false
    const flushCompletions = () => {
      completionFlushScheduled = false
      if (!pendingCompleteIds) return
      const ids = pendingCompleteIds
      pendingCompleteIds = null
      let added = false
      const next = new Set(completedRevealIds.value)
      for (const id of ids) {
        markRevealed(id)
        if (!next.has(id)) {
          next.add(id)
          added = true
        }
      }
      if (added) completedRevealIds.value = next
    }
    const handleRevealComplete = (id: string) => {
      if (!pendingCompleteIds) pendingCompleteIds = []
      pendingCompleteIds.push(id)
      if (!completionFlushScheduled) {
        completionFlushScheduled = true
        nextTick(flushCompletions)
      }
      nextTick(followOutput)
    }
    watch(messages, (msgs) => {
      if (completedRevealIds.value.size === 0) return
      const live = new Set(msgs.map(msg => msg.id))
      let changed = false
      const pruned = new Set<string>()
      for (const id of completedRevealIds.value) {
        if (live.has(id)) pruned.add(id)
        else changed = true
      }
      if (changed) completedRevealIds.value = pruned
    })
    const roomKey = computed(() => store.state.game.room_key)
    const isConnected = computed(() => store.state.game.is_connected)
    const connectionError = computed(() => store.state.game.connection_error)

    const gameTime = computed(() => store.state.game.game_time || '08:00')
    const day = computed(() => store.state.game.day || 1)
	    const season = computed(() => store.state.game.season || 'spring')
    const curfewActive = computed(() => store.state.game.curfew_active)

    const patrolWarning = computed(() => store.state.game.patrol_warning)
    const playerTrust = computed(() => store.state.game.player_trust || {})
    const playerMoney = computed(() => store.state.game.player_money || { fabi: 0, silver: 0, military_yen: 0 })
    const playerWalletFabiValue = computed(() => store.state.game.player_wallet_fabi_value || 0)
    const playerSkills = computed(() => store.state.game.player_skills || {})
    const playerDisguise = computed(() => store.state.game.player_disguise)
    const userName = computed(() => store.state.auth.username)
    const wantedLevel = computed(() => store.state.game.wanted_level)
    const hidden = computed(() => store.state.game.hidden)
    const inventory = computed(() => store.state.game.player_inventory || [])

    const currentRoom = computed(() => store.state.game.room)
	    const roomTags = computed(() => visibleRoomTags(
	      currentRoom.value?.name,
	      store.state.game.room_tags || [],
	      getTagLabel,
	      currentRoom.value?.district ? getZoneLabel(currentRoom.value.district) : undefined
	    ))
	
	    const TAG_LABELS: Record<string, string> = {
	      "bund": "The Bund", "old_city": "Old City", "hongkou": "Hongkou",
	      "french": "French Concession", "nanjing_rd": "Nanjing Road",
	      "zhabei": "Zhabei", "yangpu": "Yangpu", "xujiahui": "Xujiahui",
	      "commercial": "Commercial", "residential": "Residential",
	      "warehouse": "Warehouse", "docks": "Docks", "church": "Church",
	      "school": "School", "hidden_shanghai": "Hidden Shanghai",
	      "ccp_base": "CCP Base", "gmd_office": "GMD Office",
	      "refugee_entry": "Refugee Entry", "tutorial": "Tutorial",
	      "safe_room": "Safe Room", "crime_scene": "Crime Scene",
	      "resistance": "Resistance Network", "checkpoint": "Checkpoint",
	      "river": "Riverfront", "market": "Market", "food": "Food Available",
	    }
	
	    const getTagLabel = (tag: string): string => {
	      return TAG_LABELS[tag] || tag.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
	    }
	
	    const getZoneLabel = (district: string): string => {
	      return TAG_LABELS[district] || district.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
	    }
    const npcsInRoom = computed(() => store.state.game.room_npcs || [])
    const itemsInRoom = computed(() => store.state.game.room_items || [])

    const activeStorylets = computed(() => store.state.game.active_storylets || [])
    const now = ref(Date.now())
    let timerInterval: number | null = null
    onMounted(() => {
      timerInterval = window.setInterval(() => { now.value = Date.now() }, 1000)
    })
    onUnmounted(() => {
      if (timerInterval) clearInterval(timerInterval)
    })
    const storyletExpiryMs = (storylet: any): number =>
      storylet.expires_at
        ? storylet.expires_at * 1000
        : (storylet.triggered_at || 0) + (storylet.timer_duration || 0) * 1000
    const isStoryletExpired = (storylet: any): boolean =>
      (storylet.timer_duration || 0) > 0 && storyletExpiryMs(storylet) <= now.value

    const formatTimer = (storylet: any): string => {
      if (!storylet.timer_duration || !storylet.triggered_at) return ''
      const remaining = Math.max(0, (storyletExpiryMs(storylet) - now.value) / 1000)
      if (remaining <= 0) return '' 
      const secs = Math.ceil(remaining)
      if (secs >= 60) return `${Math.floor(secs / 60)}m ${secs % 60}s`
      return `${secs}s`
    }

    const isStoryletUrgent = (storylet: any): boolean => {
      if (!storylet.timer_duration) return false
      const expiry = storyletExpiryMs(storylet)
      return expiry > now.value && expiry - now.value <= 30_000
    }
    const activeRumors = computed(() => store.state.game.active_rumors || [])

    interface TypewriterRumour {
      id: string
      room_id: string
      speaker: string
      listener: string
      lines: string[]
      turns: { speaker: string; text: string; delay_ms: number }[]
      revealedCount: number
      revealedText: string[]
      activeTurnIndex: number
      speakerSides: Record<string, 'left' | 'right'>
      instant?: boolean
      type?: string
      dialogue?: { speaker_a: string; speaker_b: string; lines: string[] }
      text?: string
    }
    const typewriterRumours = ref<TypewriterRumour[]>([])
    const focusedRumourId = ref<string | null>(null)
    const focusRumour = (rumour: TypewriterRumour) => {
      focusedRumourId.value = rumour.speaker && rumour.listener ? rumour.id : null
    }
    const assignSpeakerSides = (turns: { speaker: string }[]): Record<string, 'left' | 'right'> => {
      const sides: Record<string, 'left' | 'right'> = {}
      for (const turn of turns) {
        if (!turn.speaker || sides[turn.speaker]) continue
        const speakerCount = Object.keys(sides).length
        sides[turn.speaker] = speakerCount === 0 || speakerCount % 2 === 0 ? 'left' : 'right'
      }
      return sides
    }
    const speakerSide = (rumour: TypewriterRumour, speaker: string): 'left' | 'right' => {
      return rumour.speakerSides[speaker] || 'left'
    }
    const overheardScheduler = createOverheardScheduler<TypewriterRumour>({
      onEnqueue: (entry) => {
        typewriterRumours.value.push(entry)
      },
      onRevealTurn: (entry, turnIndex, text, complete) => {
        const stored = typewriterRumours.value.find((candidate) => candidate.id === entry.id)
        if (!stored) return
        stored.revealedCount = Math.max(stored.revealedCount, turnIndex + 1)
        stored.revealedText[turnIndex] = text
        stored.activeTurnIndex = complete ? -1 : turnIndex
      },
      onComplete: (entry) => {
        const stored = typewriterRumours.value.find((candidate) => candidate.id === entry.id)
        if (stored) stored.activeTurnIndex = -1
      },
    })
    const clearOverheard = () => {
      overheardScheduler.clear()
      typewriterRumours.value = []
      focusedRumourId.value = null
    }
    watch(roomKey, (newRoom, oldRoom) => {
      if (newRoom !== oldRoom) clearOverheard()
    })
    onUnmounted(() => overheardScheduler.dispose())

    const activeMissions = computed(() => store.state.game.active_missions || [])

    const progressPercent = computed(() => store.state.game.progress_percent || 0)
    const ccpInfluence = computed(() => store.state.game.ccp_influence || 0)
    const gmdInfluence = computed(() => store.state.game.gmd_influence || 0)

    const completions = computed(() => store.state.game.completions || [])
    const promptText = computed(() => store.state.game.prompt_text || '> ')
    const promptSequence = computed(() => store.state.game.prompt_sequence || 0)

    const completeCommand = () => {
      if (!commandInFlight) return
      commandInFlight = false
      inputText.value = ''
      if (!store.state.popup.active) inputEl.value?.focus()
      nextTick(followOutput)
    }
    watch(promptSequence, completeCommand)

    const mapData = computed(() => store.state.game.map || {})
    const mapMode = computed(() => store.state.game.map_mode)

    const endingData = computed(() => store.state.game.ending_data)
    const serverResetNotification = computed(() => store.state.game.server_reset_notification)

    watch(() => store.state.popup.active, (active) => {
      if (active) {
        inputEl.value?.blur()
      } else {
        inputEl.value?.focus()
      }
    })

    const healthPercent = computed(() => {
      if (!player.value) return 0
      return Math.round((player.value.health / (player.value.max_health || 100)) * 100)
    })
    const hungerPercent = computed(() => {
      if (!player.value) return 0
      return Math.round((player.value.hunger / (player.value.max_hunger || 100)) * 100)
    })
    const moralePercent = computed(() => {
      if (!player.value) return 0
      return Math.round((player.value.morale / (player.value.max_morale || 100)) * 100)
    })
    const handleTravelToRoom = (roomKey: string) => {
      sendCommand('go ' + roomKey)
    }

    const sendCommand = async (cmd: string) => {
      if (commandInFlight) return
      commandInFlight = true
      commandHistory.value.unshift(cmd)
      historyIndex.value = -1
      filteredSuggestions.value = []
      activeSuggestionIndex.value = -1
      showNoMatches.value = false
      compEngine.resetCycle()
      try {
        await store.dispatch('game/cmd', cmd)
      } catch (error) {
        commandInFlight = false
        throw error
      }
    }

    const hasPendingRevealWork = (): boolean => {
      for (const msg of messages.value) {
        if (!completedRevealIds.value.has(msg.id)) return true
      }
      return false
    }
    const handleInputKeydown = (e: KeyboardEvent) => {
      hintScheduler.restart()
      if (store.state.popup.active) {
        e.preventDefault()
        return
      }
      if (e.key === ' ' || e.key === 'Enter') {
        const emptyInput = inputText.value.length === 0
        const pendingReveal = hasPendingRevealWork()
        if (pendingReveal) {
          if (emptyInput) {
            e.preventDefault()
            skipCurrentReveal()
            return
          }
        } else if (emptyInput && skipCurrentReveal()) {
          e.preventDefault()
          return
        }
      }
      const dropdownOpen = filteredSuggestions.value.length > 0
      if (e.key === 'Enter') {
        if (dropdownOpen && activeSuggestionIndex.value >= 0) {
          e.preventDefault()
          insertCompletion(filteredSuggestions.value[activeSuggestionIndex.value])
          return
        }
        const cmd = inputText.value.trim()
        if (cmd) {
          e.preventDefault()
          sendCommand(cmd)
        }
      } else if (e.key === 'ArrowUp') {
        if (dropdownOpen) {
          e.preventDefault()
          activeSuggestionIndex.value = activeSuggestionIndex.value <= 0
            ? filteredSuggestions.value.length - 1
            : activeSuggestionIndex.value - 1
        } else {
          e.preventDefault()
          if (historyIndex.value < commandHistory.value.length - 1) {
            historyIndex.value++
            inputText.value = commandHistory.value[historyIndex.value]
          }
        }
      } else if (e.key === 'ArrowDown') {
        if (dropdownOpen) {
          e.preventDefault()
          activeSuggestionIndex.value = activeSuggestionIndex.value >= filteredSuggestions.value.length - 1
            ? 0
            : activeSuggestionIndex.value + 1
        } else {
          e.preventDefault()
          if (historyIndex.value > 0) {
            historyIndex.value--
            inputText.value = commandHistory.value[historyIndex.value]
          } else if (historyIndex.value === 0) {
            historyIndex.value = -1
            inputText.value = ''
          }
        }
      } else if (e.key === 'Tab') {
        e.preventDefault()
        const result = compEngine.tab(inputText.value, e.shiftKey)
        inputText.value = result.newInput
        filteredSuggestions.value = result.suggestions
        activeSuggestionIndex.value = result.activeIndex
        showNoMatches.value = result.noMatches && result.suggestions.length === 0
        currentCategory.value = compEngine.getSuggestionCategory(inputText.value)
      } else if (e.key === 'Escape') {
        filteredSuggestions.value = []
        activeSuggestionIndex.value = -1
        showNoMatches.value = false
        compEngine.resetCycle()
      }
    }

    const reconnect = async () => {
      const uri = store.state.game.uri
      if (uri) {
        await store.dispatch('game/connect', uri)
      }
    }

    const insertCompletion = (text: string) => {
      inputText.value = compEngine.selectSuggestion(inputText.value, text)
      filteredSuggestions.value = []
      activeSuggestionIndex.value = -1
      showNoMatches.value = false
      inputEl.value?.focus()
    }

    watch(messages, () => {
      nextTick(followOutput)
    }, { deep: true })

    watch(inputText, () => {
      showNoMatches.value = false
    })

    watch(activeSuggestionIndex, async (idx) => {
      if (idx < 0) return
      await nextTick()
      const el = completionListEl.value?.querySelectorAll('.completion-option')[idx] as HTMLElement | undefined
      if (el && typeof el.scrollIntoView === 'function') {
        el.scrollIntoView({ block: 'nearest' })
      }
    })

    watch(completions, () => {
      if (store.state.game.completions_data) {
        compEngine.updateCompletions(store.state.game.completions_data)
        showNoMatches.value = false
      }
    })


    watch(isConnected, (connected) => {
      if (!connected && !connectionError.value) {
      }
      if (!connected) {
        hintScheduler.clear()
      }
    })

    watch(activeRumors, (newRumours) => {
      if (newRumours.length === 0) {
        clearOverheard()
        return
      }
      const pending: TypewriterRumour[] = []
      for (const rumour of newRumours) {
        if (rumour.room_id && roomKey.value && rumour.room_id !== roomKey.value) continue
        if ((rumour as any).type === 'ambient') {
          const turns = [{ speaker: '', text: rumour.text || '', delay_ms: 0 }]
          pending.push({
            id: rumour.id, room_id: rumour.room_id || roomKey.value || '', speaker: '', listener: '', lines: [], turns,
            revealedCount: 1, revealedText: turns.map(turn => turn.text), activeTurnIndex: -1,
            speakerSides: assignSpeakerSides(turns), instant: true, type: 'ambient',
          })
          continue
        }

        if (rumour.turns?.length) {
          const firstSpeaker = rumour.turns[0]?.speaker || ''
          const speaker = rumour.speaker || firstSpeaker
          const listener = rumour.listener || rumour.turns.find(turn => turn.speaker && turn.speaker !== speaker)?.speaker || ''
          const turns = rumour.turns.map(turn => ({
            speaker: turn.speaker || '',
            text: turn.text || '',
            delay_ms: Number(turn.delay_ms) || 0,
          }))
          pending.push({
            id: rumour.id, room_id: rumour.room_id || roomKey.value || '', speaker, listener,
            lines: turns.map(turn => turn.text), turns, revealedCount: 0,
            revealedText: turns.map(() => ''), activeTurnIndex: -1,
            speakerSides: assignSpeakerSides(turns),
            instant: Boolean((rumour as any).instant) || instantTextPreference() || prefersReducedMotion(),
            type: (rumour as any).type,
          })
          continue
        }

        const dialogue = rumour.dialogue
        const dialogueLines = Array.isArray(dialogue)
          ? dialogue
          : dialogue?.lines || rumour.lines || []
        if (dialogueLines.length) {
          const speaker = rumour.speaker || (!Array.isArray(dialogue) ? dialogue?.speaker_a : '') || 'Someone'
          const listener = rumour.listener || (!Array.isArray(dialogue) ? dialogue?.speaker_b : '') || ''
          const turns = dialogueLines.map((text, index) => ({
            speaker: index % 2 === 0 ? speaker : listener,
            text,
            delay_ms: 0,
          }))
          pending.push({
            id: rumour.id, room_id: rumour.room_id || roomKey.value || '', speaker, listener,
            lines: dialogueLines, turns, revealedCount: dialogueLines.length,
            revealedText: dialogueLines.slice(), activeTurnIndex: -1,
            speakerSides: assignSpeakerSides(turns), instant: true,
            type: (rumour as any).type,
            dialogue: !Array.isArray(dialogue) ? dialogue : undefined,
          })
          continue
        }

        const turns = [{ speaker: '', text: rumour.text || '', delay_ms: 0 }]
        pending.push({
          id: rumour.id, room_id: rumour.room_id || roomKey.value || '', speaker: '', listener: '', lines: [], turns,
          revealedCount: 1, revealedText: turns.map(turn => turn.text), activeTurnIndex: -1,
          speakerSides: assignSpeakerSides(turns), instant: true,
          type: (rumour as any).type,
        })
      }
      overheardScheduler.enqueue(pending)
    }, { deep: true, immediate: true })
    const ambientAudioEl = ref<HTMLAudioElement | null>(null)
    const effectsAudioEl = ref<HTMLAudioElement | null>(null)
    const footstepAudioEl = ref<HTMLAudioElement | null>(null)
    const audioState = computed(() => store.state.game.audio_state)
    const audioChannels = computed(() => store.state.game.audio_channels)
    let audioUnlockHooked = false
    const pendingAudioRetries: Array<() => void> = []
    const hookAudioUnlock = () => {
      if (audioUnlockHooked) return
      audioUnlockHooked = true
      const unlock = () => {
        document.removeEventListener('pointerdown', unlock)
        document.removeEventListener('keydown', unlock)
        const retries = pendingAudioRetries.splice(0)
        for (const retry of retries) retry()
      }
      document.addEventListener('pointerdown', unlock)
      document.addEventListener('keydown', unlock)
    }
    const playSoundOn = (el: HTMLAudioElement | null, sound: string, volume: number, loop: boolean, muted: boolean, restart = false) => {
      if (!el) return
      if (muted) {
        el.pause()
        return
      }
      const src = resolveAudioPath(sound)
      if (!src) return
      if (!el.src || !el.src.endsWith(src)) {
        el.src = src
      } else if (restart) {
        el.currentTime = 0
      }
      el.volume = volume
      el.loop = loop
      const playback = el.play()
      if (playback && typeof playback.catch === 'function') playback.catch(() => {
        console.log('[AUDIO] Autoplay blocked - will retry on next interaction')
        hookAudioUnlock()
        pendingAudioRetries.push(() => {
          if (el.src && el.src.endsWith(src) && !audioState.value.muted) {
            el.volume = volume
            el.loop = loop
            const retried = el.play()
            if (retried && typeof retried.catch === 'function') retried.catch(() => {})
          }
        })
      })
    }

    const footstepSequencer = createFootstepSequencer((volume: number) => {
      playSoundOn(footstepAudioEl.value, FOOTSTEP_SOUND, volume, false, audioState.value.muted, true)
    })

    const stopSoundOn = (el: HTMLAudioElement | null) => {
      if (!el) return
      el.pause()
      el.currentTime = 0
    }
    watch(audioChannels, (channels) => {
      const muted = audioState.value.muted
      const ambient = channels['ambient']
      if (ambient && ambient.playing) {
        playSoundOn(ambientAudioEl.value, ambient.sound, ambient.volume, ambient.loop, muted)
      } else {
        stopSoundOn(ambientAudioEl.value)
      }
      const effects = channels['effects']
      if (effects && effects.playing) {
        if (effects.sound === FOOTSTEP_SOUND && !effects.loop) {
          footstepSequencer.start(effects.volume)
        } else {
          playSoundOn(effectsAudioEl.value, effects.sound, effects.volume, effects.loop, muted)
        }
      } else {
        stopSoundOn(effectsAudioEl.value)
      }
    }, { deep: true })
    watch(
      () => store.state.popup.active?.kind === 'inventory',
      (open, wasOpen) => {
        if (!!open === !!wasOpen) return
        playSoundOn(effectsAudioEl.value, 'chest_close', 0.5, false, audioState.value.muted, true)
      }
    )
    watch(() => audioState.value.muted, (muted) => {
      if (muted) {
        stopSoundOn(ambientAudioEl.value)
        stopSoundOn(effectsAudioEl.value)
        stopSoundOn(footstepAudioEl.value)
      } else {
        const channels = audioChannels.value
        const ambient = channels['ambient']
        if (ambient && ambient.playing) {
          playSoundOn(ambientAudioEl.value, ambient.sound, ambient.volume, ambient.loop, false)
        }
        const effects = channels['effects']
        if (effects && effects.playing && effects.sound !== FOOTSTEP_SOUND) {
          playSoundOn(effectsAudioEl.value, effects.sound, effects.volume, effects.loop, false)
        }
      }
    })
    const toggleMute = () => {
      store.commit('game/SET_AUDIO_MUTED', !audioState.value.muted)
    }
    onUnmounted(() => footstepSequencer.cancelAll())

    const setVolume = (volume: number) => {
      store.commit('game/SET_AUDIO_VOLUME', volume)
    }

    const clearEnding = () => {
      store.commit('game/SET_ENDING_DATA', null)
    }

    onMounted(() => {
      if (!isConnected.value) {
        if (!store.state.game.uri) {
          router.push('/login')
          return
        }
      }

      inputEl.value?.focus()
    })

    onUnmounted(() => {
    })

    return {
      terminalEl,
      autoFollow,
      hasUnreadOutput,
      handleTerminalScroll,
      jumpToBottom,
      inputEl,
      ambientAudioEl,
      footstepAudioEl,
      effectsAudioEl,
      inputText,
      registerTerminalMessage,
      setRevealState,
      handleRevealProgress,
      isGated,
      hasSeenReveal,
      handleRevealComplete,
      activeTab,
      filteredSuggestions,
      activeSuggestionIndex,
      currentCategory,
      showNoMatches,
      completionListEl,
      player,
      messages,
      roomKey,
      isConnected,
      connectionError,
      gameTime,
      day,
      weather,
      season,
	      curfewActive,
		      patrolWarning,
      playerTrust,
      playerMoney,
      playerWalletFabiValue,
      playerSkills,
      playerDisguise,
      userName,
      inventory,
	      currentRoom,
	      roomTags,
	      getTagLabel,
	      getZoneLabel,
      npcsInRoom,
      itemsInRoom,
	      activeStorylets,
	      formatTimer,
	      isStoryletUrgent,
	      isStoryletExpired,
	      activeRumors,
	      typewriterRumours,
      focusedRumourId,
      focusRumour,
      speakerSide,
      activeMissions,
      progressPercent,
      ccpInfluence,
      gmdInfluence,
      completions,
      promptText,
      mapData,
      mapMode,
      healthPercent,
      hungerPercent,
      moralePercent,
      sendCommand,
      handleInputKeydown,
      handleTravelToRoom,
      reconnect,
      audioState,
      toggleMute,
      setVolume,
	      endingData,
	      serverResetNotification,
	      clearEnding,
	      wantedLevel,
	      hidden,
      getMessageStyle,
	      insertCompletion
    }
  }
})
</script>

<style lang="scss" scoped>
@import "@/styles/colors.scss";

.game-container {
  display: grid;
  grid-template-columns: 20% 60% 20%;
  height: 100vh;
  gap: 0;
  background: #111111;
}
.left-panel {
  background: #0a0a0a;
  border-right: 1px solid #1a1a1a;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.char-header {
  padding: 12px 14px;
  background: #0f0f0f;
  flex-shrink: 0;
  border-bottom: 1px solid #1a1a1a;
}

.char-name {
  font-size: 15px;
  font-weight: 600;
  color: #ffd24a;
  margin-bottom: 6px;
}

.char-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.char-tag {
  font-size: 11px;
  color: #999999;
  background: #1a1a1a;
  padding: 2px 6px;
  border-radius: 2px;
}

.wanted-tag {
  color: #ff6b6b;
  background: #2a1111;
}

.hidden-tag {
  color: #b388ff;
  background: #1a1133;
}

.map-section {
  padding: 12px;
  border-bottom: 1px solid #1a1a1a;
  flex-shrink: 0;
}

.section-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #666666;
  margin-bottom: 8px;
}

.map-wrapper {
  display: flex;
  justify-content: center;
  background: #0d0d0d;
  border: 1px solid #1a1a1a;
  border-radius: 4px;
  padding: 8px;
}

.tabbed-content {
  flex: 1 1 50%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.tab-nav {
  display: flex;
  background: #0f0f0f;
  border-bottom: 1px solid #1a1a1a;
}

.tab-btn {
  flex: 1;
  padding: 8px 4px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: #666666;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  cursor: pointer;

  &:hover { color: #cccccc; }
  &.active { color: #ffd24a; border-bottom-color: #ffd24a; }
}

.tab-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.vital-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.vital-label {
  width: 60px;
  font-size: 11px;
  color: #999999;
}

.vital-bar {
  flex: 1;
  height: 8px;
  background: #1a1a1a;
  border-radius: 4px;
  overflow: hidden;
}

.vital-fill {
  height: 100%;
  border-radius: 4px;

  &.health { background: #d77617; }
  &.hunger { background: #d77617; }
  &.morale { background: #d77617; }
}

.vital-value {
  width: 50px;
  font-size: 11px;
  color: #cccccc;
  text-align: right;
  font-family: 'Source Code Pro', monospace;
}

.currency-section {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #1a1a1a;
}

.currency-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 12px;
}

.currency-label { color: #999999; }
.currency-value {
  font-family: 'Source Code Pro', monospace;
  color: #cccccc;
}

.inventory-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.inventory-item {
  padding: 8px 10px;
  background: #151515;
  border: 1px solid #1a1a1a;
  border-radius: 3px;
  margin-bottom: 4px;
  font-size: 13px;
  color: #88cc88;
  cursor: pointer;

  &:hover {
    border-color: #ffd24a;
    color: #ffd24a;
  }
}

.stats-group { margin-bottom: 16px; }

.stat-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid #1a1a1a;
  font-size: 12px;
}

.stat-label { color: #999999; }
.stat-value { font-family: 'Source Code Pro', monospace; color: #cccccc; }

.faction-section { margin-top: 12px; }
.section-sublabel {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #666666;
  margin-bottom: 8px;
}

.faction-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 11px;
}

.faction-name {
  font-weight: 500;
  color: #cccccc;
}

.faction-value { font-family: 'Source Code Pro', monospace; color: #999999; }
.influence-section {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #1a1a1a;
}

.influence-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.influence-label {
  width: 40px;
  font-size: 11px;
  color: #999999;
}

.influence-bar {
  flex: 1;
  height: 6px;
  background: #1a1a1a;
  border-radius: 3px;
  overflow: hidden;
}

.influence-fill {
  height: 100%;
  border-radius: 3px;

  &.ccp { background: #cc4444; }
  &.gmd { background: #4488cc; }
}

.influence-value {
  width: 40px;
  font-size: 10px;
  color: #666666;
  text-align: right;
  font-family: 'Source Code Pro', monospace;
}
.rumours-panel {
  padding: 12px;
  border-top: 1px solid #1a1a1a;
  flex: 0 1 35%;
  display: flex;
  flex-direction: column;
  min-height: 120px;
  min-width: 0;
}

.rumour-scroll {
  overflow-y: auto;
  overflow-x: hidden;
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
  min-height: 0;
  min-width: 0;
}

.rumour-entry {
  padding: 10px;
  background: #151515;
  border: 1px solid #1a1a1a;
  border-radius: 4px;
  font-size: 12px;
  color: #999999;
  line-height: 1.4;
  min-width: 0;
}

.rumour-dialogue {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.rumour-dialogue-line {
  display: flex;
  width: 100%;
  min-width: 0;
  opacity: 1;
  transition: opacity 0.2s ease;
}

.rumour-dialogue-line.turn-left {
  justify-content: flex-start;
  padding-right: 14%;
}

.rumour-dialogue-line.turn-right {
  justify-content: flex-end;
  padding-left: 14%;
}

.rumour-dialogue-line.line-hidden {
  opacity: 0;
}

.rumour-dialogue-line.line-revealed {
  opacity: 1;
}

.rumour-message {
  min-width: 0;
  max-width: 82%;
}

.rumour-message.rumour-enter-ltr {
  animation: rumourEnterLtr 0.28s ease-out both;
}

.rumour-line {
  color: #bbbbbb;
  font-style: italic;
  overflow-wrap: anywhere;
}

.rumour-speaker-name {
  margin: 0 8px 4px;
  color: #999999;
  font-size: 10px;
  letter-spacing: 0.08em;
  line-height: 1.2;
  text-transform: uppercase;
}

.turn-right .rumour-speaker-name {
  text-align: right;
}

.rumour-bubble {
  padding: 8px 10px;
  border: 1px solid #292929;
  border-radius: 5px 5px 5px 2px;
  background: #171717;
  color: #bbbbbb;
  overflow-wrap: anywhere;
  white-space: normal;
}

.turn-right .rumour-bubble {
  border-radius: 5px 5px 2px 5px;
  background: #1c1b17;
}

.rumour-cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  vertical-align: -2px;
  background: #bbbbbb;
  animation: rumourCursorBlink 0.72s steps(1) infinite;
}

.rumour-entry.rumour-type-extortion,
.rumour-entry.rumour-type-intimidation {
  border-left: 2px solid #ff6644;
}
.rumour-entry.rumour-type-argument {
  border-left: 2px solid #ffaa44;
}
.rumour-entry.rumour-type-defection {
  background: #1a1a10;
  border: 1px solid #aa8800;
}
.rumour-entry.rumour-type-shuttering {
  opacity: 0.7;
}
.rumour-entry.rumour-type-ambient {
  opacity: 0.5;
  font-style: italic;
}
.rumour-warning-marker {
  color: #ff6644;
  font-weight: bold;
}
.rumour-defection-header {
  color: #d4a800;
  font-weight: bold;
  font-size: 13px;
  margin-bottom: 4px;
}
.rumour-shutter-prefix {
  color: #888888;
  font-size: 11px;
}
.rumour-ambient {
  font-style: italic;
  color: #777777;
}

@keyframes rumourEnterLtr {
  from { opacity: 0; transform: translateX(-14px); }
  to { opacity: 1; transform: translateX(0); }
}

@keyframes rumourCursorBlink {
  0%, 48% { opacity: 1; }
  49%, 100% { opacity: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .rumour-message,
  .rumour-cursor {
    animation: none;
  }
}
.center-panel {
  display: flex;
  flex-direction: column;
  background: #0d0d0d;
  overflow: hidden;
}

.location-header {
  padding: 12px 16px;
  background: #0f0f0f;
  border-bottom: 1px solid #1a1a1a;
}

.location-name {
  font-size: 16px;
  font-weight: 600;
  color: #dddddd;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.safe-room-badge {
  font-size: 10px;
  font-weight: 600;
  color: #66aa66;
  background: rgba(102, 170, 102, 0.15);
  padding: 2px 8px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.location-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: #999999;
}

.weather-info {
  color: #6688aa;
}

.curfew-badge {
  padding: 2px 8px;
  background: rgba(255, 68, 68, 0.15);
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  color: #ff4444;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.connection-error {
  padding: 10px 16px;
  background: rgba(255, 68, 68, 0.1);
  border-bottom: 1px solid rgba(255, 68, 68, 0.3);
  color: #ff4444;
  font-size: 13px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.reconnect-btn {
  padding: 4px 12px;
  background: #ff4444;
  border: none;
  border-radius: 3px;
  color: white;
  font-size: 12px;
  cursor: pointer;

  &:hover {
    background: #cc3333;
  }
}

.terminal {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.unread-jump {
  position: fixed;
  right: 24px;
  bottom: 96px;
  z-index: 30;
  padding: 6px 14px;
  border-radius: 14px;
  border: 1px solid #44dd44;
  background: rgba(20, 40, 20, 0.9);
  color: #44dd44;
  cursor: pointer;
  font-size: 13px;
}

.message-block {
  margin-bottom: 10px;
  padding: 6px 10px;
  padding-left: 14px;
  border-left: 4px solid transparent;
  border-radius: 0 3px 3px 0;
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.6;

  &.message-gated { display: none; }

  &[data-type="system"] {
    font-size: 12px;
  }
}

.msg-label {
  font-weight: 600;
  margin-right: 6px;
}

.input-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  position: relative;
  background: #0f0f0f;
  border-top: 1px solid #1a1a1a;
  position: relative;
}

.prompt { color: #c9a84c; font-weight: 600; font-size: 16px; }

.command-input {
  flex: 1;
  background: #0d0d0d;
  border: 1px solid #2a2a2a;
  border-radius: 4px;
  padding: 10px 12px;
  color: #e0e0e0;
  font-family: 'Source Code Pro', monospace;
  font-size: 14px;
  outline: none;
  &:focus { border-color: #c9a84c; }
  &::placeholder { color: #555555; }
  &:disabled { opacity: 0.5; cursor: not-allowed; }
}

.completions-dropdown {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  background: #141420;
  border: 1px solid #2a2a4e;
  border-bottom: none;
  border-radius: 4px 4px 0 0;
  max-height: 40vh;
  overflow-y: auto;
  z-index: 50;
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
}

.completion-option {
  padding: 4px 10px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #ccc;
  &.active {
    background: #2a2a5e;
    color: #fff;
  }
}

.completion-option .comp-cat {
  color: #555;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.completions-empty {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  background: #141420;
  border: 1px solid #2a2a4e; 
  border-bottom: none;
  border-radius: 4px 4px 0 0;
  padding: 6px 10px;
  color: #777;
  z-index: 50;
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
}
.right-panel {
  background: #0a0a0a;
  border-left: 1px solid #1a1a1a;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.room-info-section,
.npcs-section,
.items-section,
.storylets-section {
  padding: 12px;
  border-bottom: 1px solid #1a1a1a;
}

.room-info-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.room-info-zone {
  font-size: 14px;
  font-weight: 600;
  color: #ffd24a;
  margin-bottom: 2px;
}

.room-info-types {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 4px;
}

.room-type-badge {
  font-size: 10px;
  color: #999;
  background: #1a1a1a;
  padding: 2px 6px;
  border-radius: 2px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.room-info-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.info-badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 2px;
  cursor: help;
}

.indoors-badge {
  color: #88aacc;
  background: rgba(136, 170, 204, 0.15);
}

.outdoors-badge {
  color: #88aa66;
  background: rgba(136, 170, 102, 0.15);
}

.safe-badge {
  color: #66aa66;
  background: rgba(102, 170, 102, 0.15);
}

.hiding-badge {
  color: #b388ff;
  background: rgba(179, 136, 255, 0.15);
}

.nurse-badge {
  color: #ff8a65;
  background: rgba(255, 138, 101, 0.15);
}

.npc-list { display: flex; flex-direction: column; gap: 6px; }

.npc-card {
  padding: 10px;
  background: #151515;
  border: 1px solid #1a1a1a;
  border-radius: 4px;
}

.npc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.npc-name { font-size: 13px; color: #ffd24a; }

.npc-faction {
  font-size: 9px;
  padding: 2px 5px;
  background: #1a1a1a;
  border-radius: 2px;
  color: #666666;
}

.npc-standing {
  font-size: 10px;
  color: #666666;
  text-transform: capitalize;
}

.item-list { display: flex; flex-direction: column; gap: 4px; }

.item-btn {
  width: 100%;
  padding: 8px 10px;
  background: #151515;
  border: 1px solid #1a1a1a;
  border-radius: 3px;
  font-size: 12px;
  color: #88cc88;
  text-align: left;
  cursor: pointer;
  &:hover { border-color: #88cc88; }
}
.storylet-list { display: flex; flex-direction: column; gap: 10px; max-height: 40vh; overflow-y: auto; }

.storylet-card {
  padding: 12px;
  background: #151515;
  border: 1px solid #1a1a1a;
  border-radius: 4px;
}

.storylet-card.timer-warning {
  border-color: #ff4444;
  box-shadow: 0 0 8px rgba(255, 68, 68, 0.3);
  animation: storyletPulse 1s ease-in-out infinite alternate;
}

@keyframes storyletPulse {
  from { box-shadow: 0 0 4px rgba(255, 68, 68, 0.2); }
  to { box-shadow: 0 0 12px rgba(255, 68, 68, 0.5); }
}

.storylet-title {
  font-size: 13px;
  font-weight: 600;
  color: #c9a84c;
  margin-bottom: 6px;
}

.storylet-desc {
  font-size: 12px;
  color: #999999;
  margin-bottom: 10px;
  line-height: 1.4;
  cursor: pointer;
}

.rumour-entry.rumour-focused {
  border-color: #44ff44;
  box-shadow: inset 3px 0 #44ff44;
}

.storylet-observer {
  color: #999999;
  font-size: 12px;
  font-style: italic;
  margin-bottom: 10px;
}

.storylet-options {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.storylet-option {
  width: 100%;
  padding: 8px 12px;
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 3px;
  font-size: 12px;
  color: #cccccc;
  text-align: left;
  cursor: pointer;
  font-family: 'Source Code Pro', monospace;

  &:hover {
    border-color: #c9a84c;
    color: #c9a84c;
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}

.empty-state { color: #555555; font-size: 11px; font-style: italic; padding: 8px 0; }
.char-progress-bar {
  height: 3px;
  background: #1a1a1a;
  overflow: hidden;

  .char-progress-fill {
    height: 100%;
    background: #d77617;
    border-radius: 0 2px 2px 0;
    transition: width 0.3s ease;
  }
}
.ending-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 9999;
}

.ending-box {
  background: #111;
  border: 2px solid #d77617;
  border-radius: 8px;
  padding: 30px;
  max-width: min(500px, 80vw);
  max-height: 80vh;
  overflow-y: auto;
  text-align: center;

  h2 {
    color: #f5c983;
    font-size: 1.5rem;
    margin-bottom: 16px;
  }

  .ending-text {
    color: #ccc;
    font-size: 1.1rem;
    line-height: 1.6;
    margin-bottom: 20px;
    white-space: pre-wrap;
    max-height: 50vh;
    overflow-y: auto;
  }
}

.server-reset-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  background: #8b0000;
  color: #fff;
  text-align: center;
  padding: 8px;
  font-size: 13px;
  z-index: 9998;
}
@media (max-width: 900px) {
  .game-container { grid-template-columns: 1fr; }
  .left-panel, .right-panel { display: none; }
  .ending-box { max-width: 90vw; padding: 20px; }
}
</style>

<style lang="scss">
@import "@/styles/colors.scss";

sem[type="npc"] {
  color: $color-green-chat;
}

sem[type="item"] {
  color: $color-secondary;
}

sem[type="exit"] {
  color: $color-blue-chat;
}
</style>
