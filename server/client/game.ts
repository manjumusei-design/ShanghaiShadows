import { Module } from 'vuex'
import type { Room, Player, Message, Character, MapData } from '@/core/interfaces'
import { getMessageType, getMessageLabel } from '@/core/messageTypes'
import { createWebSocket, getWebSocket } from '@/services/websocket'

const DEBUG = typeof localStorage !== 'undefined' ? localStorage.getItem('ssl_debug') === 'true' : false

export interface ServerPlayerState {
  health: number
  hunger: number
  morale: number
  trust: Record<string, number>
  disguise: string
  game_time: string
  day: number
  progress_percent: number
  ccp_influence: number
  gmd_influence: number
  money_fabi: number
  money_silver: number
  money_military_yen: number
  wallet_fabi_value: number
  safe_room: boolean
  active_missions: ActiveMission[]
  journal_data: Record<string, any> | null
  wanted_policy?: WantedPolicy
}

export interface WantedPolicy {
  level: number
  ordinary_vendor_refuses: boolean
  black_market_markup: number
  patrol_multiplier: number
  disguise_perception_bonus: number
  curfew_arrest_bonus: number
  arrest_chance: number
}

export interface ActiveMission {
  mission_id: string
  title: string
  faction?: string
  objectives: string[]
  progress?: { current: number; target: number }
  reward?: number
}

export interface PatrolWarningState {
  stage: number
  seconds_remaining: number
  expires_at?: number
}

export interface StoryletTurn {
  speaker_npc?: string
  speaker: string
  text: string
}

export interface ActiveStorylet {
  storylet_id: string
  narrative: string
  turns?: StoryletTurn[]
  options: StoryletOption[]
  triggered_at: number
  timer_duration: number
  expires_at: number
  read_only: boolean
  room_id: string
  timer_warning?: boolean
}

export interface StoryletOption {
  text: string
  effects: Record<string, any>
  followup_storylet: string
  disabled: boolean
  disabled_reason?: string
}

export interface Rumor {
  id: string
  text: string
  factions: string[]
  districts: string[]
  type?: string 
  speaker?: string
  listener?: string
  turns?: { speaker: string; text: string; delay_ms: number }[]
  dialogue?: string[] | { speaker_a: string; speaker_b: string; lines: string[] }
  lines?: string[]
}

export interface KnownRumorHolder {
  id: string
  name: string
}

export interface KnownRumor {
  id: string
  text: string
  kind: string
  category: string
  source_npc_id: string
  source_location_id: string
  origin_faction: string
  current_faction: string
  districts: string[]
  tags: string[]
  truth_value: number
  created_day: number
  parent_id: string
  witness_npc_ids: string[]
  hop_count: number
  holders: KnownRumorHolder[]
  source_chain: string[]
}

export interface KnownRumorsState {
  generation: number
  records: Record<string, KnownRumor>
}

export interface RoomNpc {
  id: string
  name: string
  faction: string
  standing?: string
  description?: string
}

export interface RoomItem {
  id: string
  name: string
  description?: string
  takeable?: boolean
}

export interface GameState {

  uri: string
  is_connected: boolean
  connection_error: string | null
  login_complete: boolean

  player: Player | null
  player_skills: Record<string, number>
  player_level: number
  player_archetype: string | null
  player_target: Character | null
  player_trust: Record<string, number>
  player_money: { fabi: number; silver: number; military_yen: number }
  player_wallet_fabi_value: number
  player_inventory: RoomItem[]
  player_disguise: string


  map: MapData
  room: Room | null
  room_key: string | null
  room_chars: Character[]
  room_npcs: RoomNpc[]
  room_items: RoomItem[]
  room_tags: string[]
  room_exits: Record<string, string>
  factions: any[]


  messages: Message[]
  last_message: Record<string, Message>
  prompt_text: string
  ending_data: string | null
  server_reset_notification: string | null
  wanted_level: number
  wanted_policy: WantedPolicy
  hidden: boolean

  tutorial_hint: { hint_id: string; stage_id: string; room_id: string; payload: string; immediate: boolean } | null


  game_time: string
  day: number
  weather: string
  season: string
  curfew_active: boolean

  progress_percent: number
  ccp_influence: number
  gmd_influence: number

  active_storylets: ActiveStorylet[]
  active_rumors: Rumor[]
  known_rumors: KnownRumorsState
  active_missions: ActiveMission[]


	  completions: string[]
	  completions_data: any


  audio_state: {
    sound: string | null
    volume: number
    muted: boolean
    playing: boolean
    loop: boolean
  }


  audio_channels: Record<string, {
    sound: string
    volume: number
    loop: boolean
    playing: boolean
  }>

  patrol_warning: PatrolWarningState | null

}

const set_initial_state = (): GameState => ({
  uri: '',
  is_connected: false,
  connection_error: null,
  login_complete: false,

  player: null,
  player_skills: {},
  player_level: 1,
  player_archetype: null,
  player_target: null,
  player_trust: {},
  player_money: { fabi: 0, silver: 0, military_yen: 0 },
  player_wallet_fabi_value: 0,
  player_inventory: [],
  player_disguise: '',

  map: {},
  room: null,
  room_key: null,
  room_chars: [],
  room_npcs: [],
  room_items: [],
  room_tags: [],
  room_exits: {},
  factions: [],

  messages: [],
  last_message: {},
  prompt_text: '> ',
  ending_data: null,
  server_reset_notification: null,
  wanted_level: 0,
  wanted_policy: {
    level: 0,
    ordinary_vendor_refuses: false,
    black_market_markup: 1.5,
    patrol_multiplier: 1,
    disguise_perception_bonus: 0,
    curfew_arrest_bonus: 0,
    arrest_chance: 15,
  },
  hidden: false,
  tutorial_hint: null,

  game_time: '',
  day: 1,
  weather: 'clear',
  season: 'spring',
  curfew_active: false,

  progress_percent: 0,
  ccp_influence: 0,
  gmd_influence: 0,

  active_storylets: [],
  active_rumors: [],
  known_rumors: { generation: 0, records: {} },
  active_missions: [],

	  completions: [],
	  completions_data: null,

  audio_state: {
    sound: null,
    volume: parseFloat(typeof localStorage !== 'undefined' ? (localStorage.getItem('audio_volume') || '0.7') : '0.7'),
    muted: typeof localStorage !== 'undefined' ? localStorage.getItem('audio_muted') === 'true' : false,
    playing: false,
    loop: false
  },


  audio_channels: {},


  patrol_warning: null,
})

const game: Module<GameState, any> = {
  namespaced: true,

  state: set_initial_state,

  mutations: {
    RESET_STATE(state) {
      Object.assign(state, set_initial_state())
    },

    CLEAR_MESSAGES(state) {
      state.messages = []
    },

    SET_CONNECTED(state, connected: boolean) {
      state.is_connected = connected
    },

    SET_CONNECTION_ERROR(state, error: string | null) {
      state.connection_error = error
    },

    SET_URI(state, uri: string) {
      state.uri = uri
    },

    SET_MAP(state, map: MapData) {
      state.map = map
    },

    SET_ROOM(state, room: Room | null) {
      state.room = room
      const newKey = room?.key || null
      if (state.room_key !== newKey) {
        if (DEBUG) console.log('[MAP-DEBUG] SET_ROOM: room_key changing from', state.room_key, 'to', newKey)
      }
      state.room_key = newKey
    },

    SET_ROOM_KEY(state, key: string | null) {
      if (state.room_key !== key) {
        if (DEBUG) console.log('[MAP-DEBUG] SET_ROOM_KEY: changing from', state.room_key, 'to', key)
      }
      state.room_key = key
    },

    SET_ROOM_NPCS(state, npcs: RoomNpc[]) {
      state.room_npcs = npcs
    },

    SET_ROOM_ITEMS(state, items: RoomItem[]) {
      state.room_items = items
    },

    SET_ROOM_TAGS(state, tags: string[]) {
      state.room_tags = tags
    },

    SET_ROOM_EXITS(state, exits: Record<string, string>) {
      state.room_exits = exits
    },

    ADD_MESSAGE(state, message: Message) {
      state.messages.push(message)
      if (state.messages.length > 200) {
        state.messages = state.messages.slice(-200)
      }
    },

    SET_ROOM_CHARS(state, chars: Character[]) {
      state.room_chars = chars
    },

    SET_GAME_TIME(state, { time_str, day }: { time_str: string; day: number }) {
      state.game_time = time_str
      state.day = day
    },

    SET_WEATHER(state, weather: string) {
      state.weather = weather
    },

    SET_SEASON(state, season: string) {
      state.season = season
    },

    SET_PLAYER_TRUST(state, trust: Record<string, number>) {
      state.player_trust = trust
    },

    SET_PLAYER_MONEY(state, money: { fabi: number; silver: number; military_yen: number }) {
      state.player_money = money
    },

    SET_WALLET_FABI_VALUE(state, value: number) {
      state.player_wallet_fabi_value = value
    },

    SET_PLAYER_DISGUISE(state, disguise: string) {
      state.player_disguise = disguise
    },

    SET_PLAYER(state, playerData: any) {
      state.player = {
        health: playerData.health ?? 100,
        max_health: 100,
        hunger: playerData.hunger ?? 60,
        max_hunger: 100,
        morale: playerData.morale ?? 80,
        max_morale: 100,
        ...playerData,
      }
    },

    UPDATE_PLAYER_VITALS(state, vitals: { health?: number; hunger?: number; morale?: number }) {
      const player = state.player ?? {
        health: 100, max_health: 100, hunger: 60, max_hunger: 100,
        morale: 80, max_morale: 100,
      } as Player
      if (vitals.health !== undefined) player.health = vitals.health
      if (vitals.morale !== undefined) player.morale = vitals.morale
      if (vitals.hunger !== undefined) player.hunger = vitals.hunger
      state.player = player
    },

    ADD_ACTIVE_STORYLET(state, storylet: ActiveStorylet) {
      const index = state.active_storylets.findIndex(s => s.storylet_id === storylet.storylet_id)
      if (index === -1) {
        state.active_storylets.push(storylet)
      } else {
        state.active_storylets[index] = storylet
      }
    },

    REMOVE_ACTIVE_STORYLET(state, storylet_id: string) {
      state.active_storylets = state.active_storylets.filter(s => s.storylet_id !== storylet_id)
    },

    SET_ACTIVE_RUMORS(state, rumors: Rumor[]) {
      state.active_rumors = rumors
    },

    SET_KNOWN_RUMORS(state, payload: KnownRumorsState) {
      const generation = Number(payload?.generation ?? 0)
      const records = payload?.records && typeof payload.records === 'object' ? payload.records : {}
      state.known_rumors = { generation, records }
    },

    SET_ACTIVE_MISSIONS(state, missions: ActiveMission[]) {
      state.active_missions = missions
    },
    SET_PROGRESS_PERCENT(state, percent: number) {
      state.progress_percent = percent
    },

    SET_CCP_INFLUENCE(state, influence: number) {
      state.ccp_influence = influence
    },

    SET_GMD_INFLUENCE(state, influence: number) {
      state.gmd_influence = influence
    },

	    SET_COMPLETIONS(state, data: any) {
	      if (Array.isArray(data)) {
	        state.completions = data
	        state.completions_data = null
	      } else {
	        state.completions_data = data
	        const flat: string[] = []
	        if (data.verbs) flat.push(...data.verbs)
	        if (data.npcs) flat.push(...data.npcs)
	        if (data.items) flat.push(...data.items)
	        if (data.exits) flat.push(...data.exits)
	        state.completions = flat
	      }
	    },

    SET_PATROL_WARNING(state, data: PatrolWarningState | null) {
      if (!data) {
        state.patrol_warning = null
        return
      }
      const stage = Number(data.stage)
      if (stage === 3) {
        state.patrol_warning = {
          stage,
          seconds_remaining: Math.max(0, Math.trunc(Number(data.seconds_remaining) || 0)),
          ...(data.expires_at == null ? {} : { expires_at: Number(data.expires_at) }),
        }
      } else {
        state.patrol_warning = { stage, seconds_remaining: 0 }
      }
    },

    SET_TUTORIAL_HINT(state, hint: { hint_id: string; stage_id: string; room_id: string; payload: string; immediate: boolean }) {
      state.tutorial_hint = hint
    },

    CLEAR_TUTORIAL_HINT(state) {
      state.tutorial_hint = null
    },

    SET_PROMPT(state, prompt: string) {
      state.prompt_text = prompt
    },

    SET_ENDING_DATA(state, data: string | null) {
      state.ending_data = data
    },

    SET_SERVER_RESET_NOTIFICATION(state, notification: string | null) {
      state.server_reset_notification = notification
    },

    SET_WANTED_LEVEL(state, level: number) {
      state.wanted_level = level
    },

    SET_WANTED_POLICY(state, policy: WantedPolicy) {
      state.wanted_policy = policy
    },

    SET_HIDDEN(state, hidden: boolean) {
      state.hidden = hidden
    },

    SET_AUDIO_STATE(state, audio: { sound: string | null; playing: boolean; volume?: number; muted?: boolean; loop?: boolean }) {
      state.audio_state = { ...state.audio_state, ...audio }
    },

    SET_AUDIO_VOLUME(state, volume: number) {
      state.audio_state.volume = volume
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem('audio_volume', String(volume))
      }
    },

    SET_AUDIO_MUTED(state, muted: boolean) {
      state.audio_state.muted = muted
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem('audio_muted', String(muted))
      }
    },

    PLAY_AUDIO_CHANNEL(state, { channel, sound, volume, loop }: { channel: string; sound: string; volume: number; loop: boolean }) {
      state.audio_channels = {
        ...state.audio_channels,
        [channel]: { sound, volume, loop, playing: true }
      }
    },

    STOP_AUDIO_CHANNEL(state, channel: string) {
      const channels = { ...state.audio_channels }
      delete channels[channel]
      state.audio_channels = channels
    },

  },

  actions: {
    async connect({ commit, dispatch }, uri: string) {
      commit('SET_CONNECTION_ERROR', null)
      commit('SET_URI', uri)

      const ws = createWebSocket({
        uri,
        onOpen: () => {
          commit('SET_CONNECTED', true)
        },
        onMessage: (data) => {
          if (DEBUG) console.log('[WS-RECV] raw message:', JSON.stringify(data))
          dispatch('receiveMessage', data)
        },
        onClose: () => {
          commit('SET_CONNECTED', false)
          dispatch('popup/closePopup', null, { root: true })
        },
        onError: () => {
          commit('SET_CONNECTION_ERROR', 'Failed to connect to server.')
        }
      })

      return ws.connect().catch((err) => {
        commit('SET_CONNECTION_ERROR', 'Failed to connect to server.')
        throw err
      })
    },

    async disconnect({ commit, dispatch }) {
      const ws = getWebSocket()
      if (ws) {
        ws.disconnect()
        commit('SET_CONNECTED', false)
      }
      dispatch('popup/closePopup', null, { root: true })
    },

    async cmd({ commit, state }, text: string) {
      const ws = getWebSocket()
      if (DEBUG) console.log('[WS-SEND] sending:', JSON.stringify(text), 'ws connected:', ws?.isConnected())

      if (state.active_storylets.length > 0) {
        if (ws?.isConnected()) {
          ws.send(text)
        }
        return
      }

      const message: Message = {
        id: Date.now().toString(36) + Math.random().toString(36).substr(2, 5),
        type: 'command',
        text: '> ' + text,
        timestamp: Date.now()
      }
      commit('ADD_MESSAGE', message)

      if (ws?.isConnected()) {
        ws.send(text)
      } else {
        console.error('[WS-SEND] WebSocket not open! readyState:', ws?.getReadyState())
      }
    },


    async receiveMessage({ commit, dispatch, state }, data: any) {
      const msgType = data.type
      if (DEBUG) console.log('[WS-MSG] type:', msgType, 'payload:', JSON.stringify(data.payload || data.text || '').substring(0, 200))

	      if (msgType === 'display' && data.payload) {
	        if (DEBUG) console.log('[DEBUG] Raw display payload (first 300 chars):', data.payload.substring(0, 300))
	      }

      switch (msgType) {
        case 'display':
          dispatch('handleDisplay', data)
          if (data.payload) {
            const payload = data.payload.toLowerCase()
            if (payload.includes('password') || payload.includes('new account') ||
                payload.includes('character slot') || payload.includes('connected as') ||
                payload.includes('invalid password')) {
	              if (DEBUG) console.log('[AUTH] dispatching handleLoginPrompt from display:', payload.substring(0, 80))
              dispatch('auth/handleLoginPrompt', data.payload, { root: true })
            }
          }
          break

        case 'hint':
          commit('SET_TUTORIAL_HINT', {
            hint_id: data.hint_id || '',
            stage_id: data.stage_id || '',
            room_id: data.room_id || '',
            payload: data.payload || '',
            immediate: !!data.immediate,
          })
          break

        case 'hint_clear':
          commit('CLEAR_TUTORIAL_HINT')
          break

        case 'npc_speech':
          commit('ADD_MESSAGE', {
            id: Date.now().toString(36) + Math.random().toString(36).substr(2, 5),
            type: 'npc',
            text: `${data.speaker || ''} says, "${data.text || ''}"`,
            timestamp: Date.now(),
            label: '',
          })
          break

        case 'state':
          dispatch('handleState', data)
          break

        case 'prompt':
          commit('SET_PROMPT', data.payload || '> ')
          if (data.payload) {
            const prompt = data.payload.toLowerCase()
            if (prompt.includes('password') || prompt.includes('character') ||
                prompt.includes('new account') || prompt.includes('connected as') ||
                prompt.includes('invalid password')) {
	              if (DEBUG) console.log('[AUTH] dispatching handleLoginPrompt from prompt:', prompt.substring(0, 80))
              dispatch('auth/handleLoginPrompt', data.payload, { root: true })
            }
          }
          break

	        case 'completions': {
	          commit('SET_COMPLETIONS', data.payload || { verbs: [], npcs: [], items: [], exits: [] })
	          break
	        }

        case 'store_menu':
        case 'inventory_menu':
        case 'equipment_menu':
        case 'container_menu':
        case 'stash_menu':
        case 'action_menu':
          dispatch('popup/handleServerMessage', { type: msgType, payload: data.payload }, { root: true })
          break

        case 'popup_close':
          dispatch('popup/handleServerMessage', { type: 'popup_close', payload: data.payload }, { root: true })
          break

        case 'journal_menu':
          dispatch('popup/handleServerMessage', { type: 'journal_menu', payload: data.payload }, { root: true })
          break

        case 'map_data':
	          if (DEBUG) console.log('[MAP-DEBUG] map_data received:', {
	            roomCount: data.rooms ? Object.keys(data.rooms).length : 0,
	            roomKeys: data.rooms ? Object.keys(data.rooms).slice(0, 10) : [],
	            current_room: data.current_room
	          })
	          commit('SET_MAP', data.rooms || {})
	          if (data.current_room) {
	            if (DEBUG) console.log('[MAP-DEBUG] Setting room_key to:', data.current_room)
	            commit('SET_ROOM_KEY', data.current_room)
	          }
	          if (data.current_room && data.rooms) {
	            const hasKey = data.current_room in data.rooms
	            if (DEBUG) console.log('[MAP-DEBUG] current_room exists in rooms map?', hasKey, 'key:', data.current_room)
	            if (!hasKey) {
	              console.warn('[MAP-DEBUG] MISMATCH! current_room not found in rooms. Available keys sample:', Object.keys(data.rooms).slice(0, 5))
	            }
	          }
	          break

        case 'room_players':
          commit('SET_ROOM_CHARS', (data.payload || []).map((name: string) => ({ key: name, name, is_player: false })))
          break

        case 'room_details':
          dispatch('handleRoomDetails', data)
          break

        case 'rumors':
          commit('SET_ACTIVE_RUMORS', data.payload || [])
          break

        case 'rumor_web':
          commit('SET_KNOWN_RUMORS', data.payload || { generation: 0, records: {} })
          break

        case 'storylet':
          commit('ADD_ACTIVE_STORYLET', {
            storylet_id: data.storylet_id,
            narrative: data.narrative,
            options: data.options || [],
            triggered_at: Date.now(),
	            timer_duration: data.timer_duration,
	            expires_at: data.expires_at || 0,
            read_only: Boolean(data.read_only),
            turns: data.turns || [],
            room_id: ''
          })
          break

        case 'storylet_resolved':
          commit('REMOVE_ACTIVE_STORYLET', data.storylet_id)
          break

        case 'audio':
          {
            const soundName = data.sound || ''
            const baseName = soundName.replace(/_start$|_stop$/g, '')
            const AMBIENT_SOUNDS = ['rain', 'rain_indoor', 'storm', 'fog', 'snow', 'ambient_city', 'villager_murmur', 'temple_bell']
            const isAmbient = AMBIENT_SOUNDS.includes(baseName)
            const isStop = soundName.endsWith('_stop')
            const channel = isAmbient ? 'ambient' : 'effects'

            if (isStop) {
              commit('STOP_AUDIO_CHANNEL', channel)
            } else {
              commit('PLAY_AUDIO_CHANNEL', {
                channel,
                sound: soundName,
                volume: data.volume ?? state.audio_state.volume,
                loop: data.loop ?? isAmbient
              })
            }

            commit('SET_AUDIO_STATE', {
              sound: soundName,
              volume: data.volume ?? state.audio_state.volume,
              muted: state.audio_state.muted,
              playing: !isStop,
              loop: data.loop ?? isAmbient
            })
          }
	          break

        case 'ending':
          commit('SET_ENDING_DATA', data.payload || data.text || '')
          break

        case 'server_reset':
          commit('SET_SERVER_RESET_NOTIFICATION', data.payload || 'Server reset — reconnecting...')
          break


        case 'patrol_warning':
          commit('SET_PATROL_WARNING', {
            stage: data.stage,
            seconds_remaining: data.seconds_remaining,
            expires_at: data.expires_at == null ? undefined : Number(data.expires_at),
          })
          break

        case 'patrol_warning_clear':
          commit('SET_PATROL_WARNING', null)
          break

	        default:
          if (data.payload || data.text) {
            const message: Message = {
              id: Date.now().toString(36) + Math.random().toString(36).substr(2, 5),
              type: data.type || 'unknown',
              text: data.payload || data.text || '',
              timestamp: Date.now()
            }
            commit('ADD_MESSAGE', message)
          }
      }
    },

    handleDisplay({ commit }, data: { payload: string; msg_type?: string; instant_reveal?: boolean }) {
      const serverType = data.msg_type || 'default'
      const displayType = getMessageType(serverType)
      if (DEBUG) console.log('[DEBUG] handleDisplay: msg_type=' + serverType + ', displayType=' + displayType + ', text preview=' + (data.payload || '').substring(0, 100))

      const message: Message = {
        id: Date.now().toString(36) + Math.random().toString(36).substr(2, 5),
        type: displayType,
        text: data.payload,
        timestamp: Date.now(),
        label: getMessageLabel(displayType),
        instant_reveal: data.instant_reveal === true
      }
      commit('ADD_MESSAGE', message)
    },

    handleState({ commit, state }, data: any) {
      if (data.health !== undefined) {
        commit('UPDATE_PLAYER_VITALS', {
          health: data.health,
          hunger: data.hunger,
          morale: data.morale
        })
      }

      if (data.trust) {
        commit('SET_PLAYER_TRUST', data.trust)
      }

      if (data.money_fabi !== undefined) {
        commit('SET_PLAYER_MONEY', {
          fabi: data.money_fabi,
          silver: data.money_silver || 0,
          military_yen: data.money_military_yen || 0
        })
      }
      if (data.wallet_fabi_value !== undefined) {
        commit('SET_WALLET_FABI_VALUE', data.wallet_fabi_value)
      }

      if (data.game_time) {
        commit('SET_GAME_TIME', {
          time_str: data.game_time,
          day: data.day || 1
        })
      }

      if (data.disguise !== undefined) {
        commit('SET_PLAYER_DISGUISE', data.disguise)
      }

      if (data.weather) {
        commit('SET_WEATHER', data.weather)
      }
      if (data.season) {
        commit('SET_SEASON', data.season)
      }

      if (data.progress_percent !== undefined) {
        commit('SET_PROGRESS_PERCENT', data.progress_percent)
      }
      if (data.ccp_influence !== undefined) {
        commit('SET_CCP_INFLUENCE', data.ccp_influence)
      }
      if (data.gmd_influence !== undefined) {
        commit('SET_GMD_INFLUENCE', data.gmd_influence)
      }

      if (data.active_missions) {
        commit('SET_ACTIVE_MISSIONS', data.active_missions)
      }

      if (data.safe_room !== undefined && state.room) {
        commit('SET_ROOM', { ...state.room, safe: data.safe_room })
      }

      if (data.wanted_level !== undefined) {
        commit('SET_WANTED_LEVEL', data.wanted_level)
      }
      if (data.wanted_policy !== undefined) {
        commit('SET_WANTED_POLICY', data.wanted_policy)
      }

      if (data.hidden !== undefined) {
        commit('SET_HIDDEN', data.hidden)
      }

    },

    handleRoomDetails({ commit }, payload: any) {
      if (payload.title) {
        const roomObj = {
          ...payload,
          key: payload.room_id,
          name: payload.title
        } as Room
        if (DEBUG) console.log('[MAP-DEBUG] handleRoomDetails: SET_ROOM with key:', payload.room_id, '(this sets room_key)')
        commit('SET_ROOM', roomObj)
      }
      if (payload.tags) {
        commit('SET_ROOM_TAGS', payload.tags)
      }
      if (payload.items) {
        commit('SET_ROOM_ITEMS', payload.items)
      }
      if (payload.npcs) {
        commit('SET_ROOM_NPCS', payload.npcs)
      }
      if (payload.exits) {
        commit('SET_ROOM_EXITS', payload.exits)
      }
    }
  }
}

export default game
