import type { Module } from 'vuex'

export interface ItemRow {
  id: string
  name: string
  description?: string
  category?: string
  rarity?: string
  takeable?: boolean
  is_weapon?: boolean
  weapon_type?: string
  courage_bonus?: number
  is_armour?: boolean
  defense_value?: number
  durability?: number
  max_durability?: number
  mods?: string[]
  food_value?: number
  morale_restore?: number
  is_container?: boolean
  is_open?: boolean
  locked?: boolean
  key_id?: string
  opens_container?: string
  is_note?: boolean
  is_map?: boolean
  is_money?: boolean
  is_key?: boolean
  is_quest_item?: boolean
  contraband_risk?: boolean
  price?: number
  currency?: string
  section?: string
  affordable?: boolean
  equipped?: 'weapon' | 'armour' | 'disguise' | null
}

export interface StoreItem extends ItemRow {
  price: number
  currency: string
  affordable: boolean
}

export interface StorePayload {
  generation: number
  vendor_id: string
  vendor_name: string
  room_key: string
  currency: string
  wallet_fabi_value: number
  items: StoreItem[]
  cancel_label?: string
  black_market_available: boolean
}

export interface InventoryItem extends ItemRow {
  instance_id: string
  equipped?: 'weapon' | 'armour' | 'disguise' | null
  actions: string[]
}

export interface InventoryPayload {
  generation: number
  slots_used: number
  slots_max: number
  equipped: { weapon_id: string | null; armour_id: string | null; disguise: string | null }
  wallet_fabi_value: number
  money_fabi: number
  money_silver: number
  money_military_yen: number
  items: InventoryItem[]
}

export interface EquipmentPayload {
  generation: number
  weapon: ItemRow | null
  armour: ItemRow | null
  disguise: string | null
  eligible: ItemRow[]
}

export interface ContainerItem extends ItemRow {
  instance_id: string
}

export interface ContainerPayload {
  generation: number
  container_id: string
  name: string
  description?: string
  room_key: string
  is_open: boolean
  locked: boolean
  key_id?: string
  key_name?: string
  has_key?: boolean
  items: ContainerItem[]
}

export interface StashPayload {
  generation: number
  safehouse_name: string
  room_key: string
  retrieval_note?: string
  items: ItemRow[]
}

export interface JournalPayload {
  generation: number
  events: any[]
  known_rumours: Record<string, {
    id: string
    text?: string
    [key: string]: unknown
  }>
  conversations: any[]
  intel: { npc_id: string; npc_name: string; label: string }[]
  testimonies: {
    id: string
    title: string
    date: string
    place: string
    writer: string
    source: string
    source_type: string
    source_badge: string
    text: string
    read_day?: number
  }[]
  testimony_summary?: string
  tutorial_lessons?: Record<string, string>
  active_missions: any[]
  summary: string
}

export interface ActionItem extends ItemRow {
  identity: string
  disabled?: boolean
  disabled_reason?: string
}

export interface ActionPayload {
  generation: number
  room_key: string
  action: string
  title: string
  stage?: string
  note?: string
  confirm_target?: string
  items: ActionItem[]
}

export type PopupKind = 'store' | 'inventory' | 'equipment' | 'container' | 'stash' | 'journal' | 'action'

export type PopupInstance =
  | { kind: 'store'; generation: number; context: { room_key: string }; payload: StorePayload }
  | { kind: 'inventory'; generation: number; payload: InventoryPayload }
  | { kind: 'equipment'; generation: number; payload: EquipmentPayload }
  | { kind: 'container'; generation: number; context: { room_key: string }; payload: ContainerPayload }
  | { kind: 'stash'; generation: number; context: { room_key: string }; payload: StashPayload }
  | { kind: 'journal'; generation: number; payload: JournalPayload }
  | { kind: 'action'; generation: number; context: { room_key: string }; payload: ActionPayload }

export interface PopupState {
  active: PopupInstance | null
}

export interface PopupActionFields {
  action: string
  target_id?: string
  context_id?: string
  room_key?: string
  stage?: string
}

export function buildPopupAction(active: PopupInstance, fields: PopupActionFields): string {
  const message: Record<string, unknown> = {
    type: 'popup_action',
    popup: active.kind,
    generation: active.generation,
    action: fields.action,
  }
  if (fields.target_id !== undefined) message.target_id = fields.target_id
  if (fields.context_id !== undefined) message.context_id = fields.context_id
  if (fields.room_key !== undefined) message.room_key = fields.room_key
  if (fields.stage !== undefined) message.stage = fields.stage
  return JSON.stringify(message)
}

const KIND_BY_TYPE: Record<string, PopupKind> = {
  store_menu: 'store',
  inventory_menu: 'inventory',
  equipment_menu: 'equipment',
  container_menu: 'container',
  stash_menu: 'stash',
  journal_menu: 'journal',
  action_menu: 'action',
}

const CONTEXT_BOUND: PopupKind[] = ['store', 'container', 'stash', 'action']

const popup: Module<PopupState, any> = {
  namespaced: true,

  state: (): PopupState => ({ active: null }),

  mutations: {
    OPEN_POPUP(state, { kind, payload }: { kind: PopupKind; payload: any }) {
      const instance: any = { kind, generation: payload.generation ?? 0, payload }
      if (CONTEXT_BOUND.includes(kind)) {
        instance.context = { room_key: payload.room_key ?? '' }
      }
      state.active = instance
    },

    REPLACE_PAYLOAD(state, payload: any) {
      if (!state.active) return
      state.active.payload = payload
      state.active.generation = payload.generation ?? state.active.generation
      if (state.active.context && payload.room_key) {
        state.active.context.room_key = payload.room_key
      }
    },

    CLOSE_POPUP(state) {
      state.active = null
    },
  },

  actions: {
    handleServerMessage({ commit, state }, { type, payload }: { type: string; payload: any }) {
      if (type === 'popup_close') {
        commit('CLOSE_POPUP')
        return
      }
      const kind = KIND_BY_TYPE[type]
      if (!kind || !payload) return
      if (state.active && state.active.kind === kind) {
        commit('REPLACE_PAYLOAD', payload)
      } else {
        commit('OPEN_POPUP', { kind, payload })
      }
    },

    closePopup({ commit }) {
      commit('CLOSE_POPUP')
    },

    async sendPopupAction({ state }, fields: PopupActionFields) {
      const active = state.active
      if (!active) return
      const { getWebSocket } = await import('../../services/websocket')
      const ws = getWebSocket()
      if (!ws) return
      ws.send(buildPopupAction(active, fields))
    },
  },
}

export default popup
