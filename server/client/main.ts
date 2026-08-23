import { createApp, h } from 'vue'
import { createStore } from 'vuex'
import PopupHost from '../src/components/popup/PopupHost.vue'
import popupModule from '../src/store/modules/popup'

const FIXTURES: Record<string, { kind: string; payload: any }> = {
  store: {
    kind: 'store',
    payload: {
      generation: 1,
      vendor_id: 'zhang_lan',
      vendor_name: 'Zhang Lan',
      room_key: 'refugee_entry_tea_house',
      currency: 'fabi',
      items: [
        {
          id: 'baozi', name: 'baozi', description: 'A steamed bun, still warm, the pleats pinched shut over a filling of pork and scallion. The paper wrapper is slick with steam and fat.',
          price: 17, currency: 'fabi', rarity: 'common', food_value: 25, morale_restore: 5,
        },
        {
          id: 'rice_bowl', name: 'a bowl of rice', description: 'A simple ceramic bowl, glazed a pale celadon green, heaped with steaming rice. A few grains cling to the rim.',
          price: 10, currency: 'fabi', rarity: 'common', food_value: 5, morale_restore: 3,
        },
        {
          id: 'wooden_club', name: 'a wooden club', description: 'A stout piece of lumber, wrapped in cloth at the grip. Silent as a threat and always ready for a quick answer.',
          price: 25, currency: 'fabi', rarity: 'common', is_weapon: true, weapon_type: 'melee', courage_bonus: 5,
          durability: 80, max_durability: 80,
        },
        {
          id: 'quilted_jacket', name: 'a padded quilted jacket', description: 'Layers of cotton are quilted between faded cloth panels, padded thick enough to turn a knife in a crowd.',
          price: 60, currency: 'fabi', rarity: 'uncommon', is_armour: true, defense_value: 3,
          durability: 50, max_durability: 50,
        },
        {
          id: 'japanese_officer_uniform', name: "a Japanese officer's uniform", description: 'A pressed tunic with collar insignia. Wearing it in the wrong lane is a sentence only the alley decides.',
          price: 450, currency: 'military_yen', rarity: 'rare', is_armour: true, defense_value: 2,
        },
        {
          id: 'newspaper', name: "yesterday's newspaper", description: 'A single sheet of newsprint, the ink already smudging on the back of your hand.',
          price: 2, currency: 'fabi', rarity: 'common',
        },
      ],
      black_market_available: false,
    },
  },
  inventory: {
    kind: 'inventory',
    payload: {
      generation: 2,
      slots_used: 4,
      slots_max: 12,
      equipped: { weapon_id: 'wooden_club', armour_id: 'quilted_jacket', disguise: null },
      items: [
        {
          id: 'wooden_club', name: 'a wooden club', description: 'A stout piece of lumber, wrapped in cloth at the grip.', is_weapon: true, weapon_type: 'melee', courage_bonus: 5,
          durability: 80, max_durability: 80, equipped: 'weapon', actions: ['remove', 'examine'],
        },
        {
          id: 'quilted_jacket', name: 'a padded quilted jacket', description: 'Layers of cotton are quilted between faded cloth panels.', is_armour: true, defense_value: 3,
          durability: 50, max_durability: 50, equipped: 'armour', actions: ['remove', 'examine'],
        },
        {
          id: 'baozi', name: 'baozi', description: 'A steamed bun, still warm, the pleats pinched shut over a filling of pork and scallion.',
          food_value: 25, morale_restore: 5, equipped: null, actions: ['eat', 'examine'],
        },
        {
          id: 'safe_key', name: 'a small brass key', description: 'A small brass key, worn bright along the teeth, that opens the lockbox behind the counter.',
          is_key: true, equipped: null, actions: ['drop', 'examine'],
        },
        {
          id: 'ledger', name: 'a ledger', description: 'A clothbound ledger with handwritten rows of names, dates and amounts. The ink is old and the hand is careful.',
          is_note: true, equipped: null, actions: ['read', 'examine'],
        },
      ],
    },
  },
  equipment: {
    kind: 'equipment',
    payload: {
      generation: 3,
      weapon: {
        id: 'wooden_club', name: 'a wooden club', description: 'A stout piece of lumber, wrapped in cloth at the grip.',
        is_weapon: true, weapon_type: 'melee', courage_bonus: 5, durability: 80, max_durability: 80,
      },
      armour: null,
      disguise: 'coolie',
      eligible: [
        {
          id: 'iron_pipe', name: 'an iron pipe', description: 'A length of heavy iron pipe, one end flattened from use.', is_weapon: true, courage_bonus: 3,
        },
        {
          id: 'quilted_jacket', name: 'a padded quilted jacket', description: 'Layers of cotton are quilted between faded cloth panels.', is_armour: true, defense_value: 3,
        },
      ],
    },
  },
  container: {
    kind: 'container',
    payload: {
      generation: 4,
      container_id: 'wooden_crate',
      name: 'a wooden crate',
      description: 'A nailed-shut shipping crate stamped with a customs mark that has half worn away.',
      room_key: 'refugee_entry_back_alley',
      is_open: true,
      locked: false,
      items: [
        {
          id: 'ledger', name: 'a ledger', description: 'A clothbound ledger with handwritten rows of names, dates and amounts.', is_note: true,
        },
        {
          id: 'candle', name: 'a tallow candle', description: 'A hand-rolled tallow candle, the wick trimmed short for travel.',
        },
      ],
    },
  },
  stash: {
    kind: 'stash',
    payload: {
      generation: 5,
      safehouse_name: 'The Riverside Flats',
      room_key: 'refugee_entry_safehouse',
      retrieval_note: 'RETRIEVE withdraws all stored items at once.',
      items: [
        {
          id: 'quilted_jacket', name: 'a padded quilted jacket', description: 'Layers of cotton are quilted between faded cloth panels, padded thick enough to turn a knife in a crowd.',
          is_armour: true, defense_value: 3, durability: 50, max_durability: 50,
        },
        {
          id: 'rice_bowl', name: 'a bowl of rice', description: 'A simple ceramic bowl, glazed a pale celadon green, heaped with steaming rice.',
          food_value: 5, morale_restore: 3,
        },
        {
          id: 'safe_key', name: 'a small brass key', description: 'A small brass key, worn bright along the teeth, that opens the lockbox behind the counter.',
          is_key: true,
        },
      ],
    },
  },
  journal: {
    kind: 'journal',
    payload: {
      generation: 6,
      events: [
        { day: 2, minute: 480, text: 'A raid on the Bund.' },
        { day: 2, minute: 500, text: 'Rice prices rose in the market.' },
        { day: 2, minute: 510, text: 'The patrol changed shifts early, and the streets emptied.' },
        { day: 2, minute: 530, text: 'A merchant on Nanking Road bought silence at a high price.' },
      ],
      rumours: [
        { npc_id: '_rumor', npc_response: 'The docks are whispering about the customs men and a shipment nobody saw.' },
        { npc_id: '_rumor', npc_response: 'Someone says the safehouse cellar flooded again last spring.' },
      ],
      conversations: [
        { npc_id: 'zhang_lan', npc_response: 'Zhang Lan talks about the noodle cart and the kempeitai patrol schedule.' },
        { npc_id: 'old_chen', npc_response: 'Old Chen remembers the tea house before the occupation, and the prices since.' },
      ],
      intel: {
        zhang_lan: { smuggling: { npc_name: 'Zhang Lan' }, patrol_route: { npc_name: 'Zhang Lan' } },
      },
      active_missions: [{ mission_id: 'deliver_rice' }, { mission_id: 'smuggle_ledger' }],
      summary: '',
    },
  },
}

const params = new URLSearchParams(window.location.search)
const kind = params.get('popup') || 'store'
const fixture = FIXTURES[kind] || FIXTURES.store
if (params.get('short') === '1') {
  fixture.payload.items = (fixture.payload.items || []).map((item: any) => ({
    ...item,
    description: 'A short description.',
  }))
}
if (params.get('long') === '1' && fixture.payload.items) {
  const pad = Array.from({ length: 40 }, (_, i) => `Line ${i + 1}: The description runs on, detail after detail, filling the pane until it must scroll.`).join(' ')
  fixture.payload.items[0] = { ...fixture.payload.items[0], description: pad }
}

const store = createStore({
  modules: {
    popup: popupModule,
    game: {
      namespaced: true,
      state: () => ({
        player_money: { fabi: 50, silver: 0, military_yen: 30 },
        room_key: fixture.payload.room_key || 'refugee_entry_tea_house',
        room: {
          key: fixture.payload.room_key || 'refugee_entry_tea_house',
          name:
            fixture.kind === 'store' ? 'Tea House'
            : fixture.kind === 'container' ? 'Back Alley'
            : fixture.kind === 'stash' ? 'Safehouse Cellar'
            : 'Market Street',
        },
        player_disguise: fixture.kind === 'equipment' ? 'a dock coolie' : '',
        active_missions: [
          { mission_id: 'deliver_rice', title: 'Deliver the Rice' },
          { mission_id: 'smuggle_ledger', title: 'Smuggle the Ledger' },
        ],
        game_time: '10:00',
        day: 3,
      }),
    },
  },
})

window.addEventListener('error', (event) => {
  document.title = 'ERROR: ' + event.message
})

try {
  store.commit('popup/OPEN_POPUP', fixture)
} catch (err) {
  document.title = 'COMMIT FAILED: ' + String(err)
}

const app = createApp({
  render: () => h(PopupHost),
})
app.config.errorHandler = (err) => {
  document.title = 'VUE ERROR: ' + String(err)
}
app.use(store)
app.mount('#app')

document.title = 'READY ' + kind + ' active=' + JSON.stringify(store.state.popup.active && store.state.popup.active.kind)

Promise.resolve().then(async () => {
  const region = document.querySelector('.list-popup-list') || document.querySelector('.journal-tabs')
  if (!region) return
  const key = kind === 'journal' ? 'ArrowRight' : 'ArrowDown'
  region.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
  await Promise.resolve()
  const tabs = Array.from(document.querySelectorAll('.journal-tab'))
  const tabIdx = tabs.indexOf(document.querySelector('.journal-tab--active'))
  const rows = Array.from(document.querySelectorAll('.list-row'))
  const rowIdx = rows.indexOf(document.querySelector('.list-row--active'))
  const highlightAfterKey = kind === 'journal' ? tabIdx : rowIdx
  document.title += ' KEYAFTER=' + highlightAfterKey
})

{
  const panel = document.querySelector('.popup-panel') as HTMLElement | null
  document.title = 'PROBE panel=' + String(!!panel) + ' overlays=' + document.querySelectorAll('.popup-overlay').length + ' appHTML=' + JSON.stringify(document.getElementById('app')?.innerHTML.slice(0, 80))
  if (panel) {
    const overlay = document.querySelector('.popup-overlay') as HTMLElement | null
    const layout = document.querySelector('.store-layout') as HTMLElement | null
    const row = document.querySelector('.list-row--active') as HTMLElement | null
    const buy = Array.from(document.querySelectorAll('.popup-action')).find(
      (el) => el.textContent === 'Buy'
    ) as HTMLElement | null
    const meta = document.querySelector('.popup-meta') as HTMLElement | null
    const rowStyle = row ? getComputedStyle(row) : null
    const buyStyle = buy ? getComputedStyle(buy) : null
    const report = {
      panelWidth: panel.getBoundingClientRect().width,
      overlayBg: overlay ? getComputedStyle(overlay).backgroundColor : null,
      overlayZ: overlay ? getComputedStyle(overlay).zIndex : null,
      gridColumns: layout ? getComputedStyle(layout).gridTemplateColumns : null,
      selectedRow: row
        ? {
            background: rowStyle && rowStyle.backgroundColor,
            boxShadow: rowStyle && rowStyle.boxShadow,
            color: rowStyle && rowStyle.color,
            width: row.getBoundingClientRect().width,
            x: Math.round(row.getBoundingClientRect().left),
          }
        : null,
      buyButton: buy
        ? {
            background: buyStyle && buyStyle.backgroundImage,
            color: buyStyle && buyStyle.color,
            disabled: buy ? (buy as HTMLButtonElement).disabled : null,
          }
        : null,
      metaText: meta ? meta.textContent : null,
      bodyText: (document.querySelector('.popup-body') as HTMLElement | null)?.innerText || '',
      backdropIsFullscreen: overlay ? overlay.getBoundingClientRect().width >= window.innerWidth : false,
      layout: {
        panelHeight: Math.round(panel.getBoundingClientRect().height),
        viewport: [window.innerWidth, window.innerHeight],
        body: (() => {
          const b = document.querySelector('.popup-body') as HTMLElement | null
          return b ? [Math.round(b.clientHeight), Math.round(b.scrollHeight)] : null
        })(),
        storeLayout: layout ? [Math.round(layout.getBoundingClientRect().height), layout.clientHeight] : null,
        details: (() => {
          const d = document.querySelector('.store-details-pane .item-details') as HTMLElement | null
          return d ? [Math.round(d.clientHeight), Math.round(d.scrollHeight)] : null
        })(),
        buyY: buy ? Math.round(buy.getBoundingClientRect().top) : null,
      },
      keys: (() => {
        const region = document.querySelector('.list-popup-list') || document.querySelector('.journal-tabs')
        if (!region) return null
        const focusedOnOpen = document.activeElement === region || (region as HTMLElement).contains(document.activeElement)
        return { focusedOnOpen, buttons: Array.from(document.querySelectorAll('.popup-action')).map((b) => b.textContent) }
      })(),
    }
    document.title = 'REPORT ' + encodeURIComponent(JSON.stringify(report))
  }
}
