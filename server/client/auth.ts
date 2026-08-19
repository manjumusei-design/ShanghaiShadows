import { Module } from 'vuex'

const DEBUG = typeof localStorage !== 'undefined' ? localStorage.getItem('ssl_debug') === 'true' : false

export interface AuthState {
  username: string | null
  characterSlot: string | null
  loginStage: 'username' | 'password' | 'character' | 'connected' | 'error'
  loginError: string | null
  isLoggingIn: boolean
}

const auth: Module<AuthState, any> = {
  namespaced: true,

  state: {
    username: null,
    characterSlot: null,
    loginStage: 'username',
    loginError: null,
    isLoggingIn: false
  },

  mutations: {
    SET_USERNAME(state, username: string | null) {
      state.username = username
    },

    SET_CHARACTER_SLOT(state, slot: string | null) {
      state.characterSlot = slot
    },

    SET_LOGIN_STAGE(state, stage: AuthState['loginStage']) {
      state.loginStage = stage
    },

    SET_LOGIN_ERROR(state, error: string | null) {
      state.loginError = error
      if (error) {
        state.loginStage = 'error'
      }
    },

    SET_LOGGING_IN(state, isLoggingIn: boolean) {
      state.isLoggingIn = isLoggingIn
    },

    RESET_AUTH(state) {
      state.username = null
      state.characterSlot = null
      state.loginStage = 'username'
      state.loginError = null
      state.isLoggingIn = false
    }
  },

  actions: {
    async startLogin({ commit, dispatch }, { uri, username }: { uri: string; username: string }) {
      if (DEBUG) console.log('[AUTH] startLogin called with uri:', uri, 'username:', username)
      commit('SET_LOGGING_IN', true)
      commit('SET_LOGIN_ERROR', null)
      commit('SET_USERNAME', username.toLowerCase())

      try {
        await dispatch('game/connect', uri, { root: true })
        if (DEBUG) console.log('[AUTH] WebSocket connected, sending username')
        await dispatch('game/cmd', username.toLowerCase(), { root: true })
        if (DEBUG) console.log('[AUTH] username sent, waiting for server response')
        return { success: true }
      } catch (e: any) {
        console.error('[AUTH] startLogin failed:', e)
        commit('SET_LOGIN_ERROR', 'Failed to connect to server')
        commit('SET_LOGGING_IN', false)
        return { success: false, error: 'Connection failed' }
      }
    },
    async handleLoginPrompt({ commit, state }, prompt: string) {
      const lowerPrompt = prompt.toLowerCase()
	      if (DEBUG) console.log('[AUTH] handleLoginPrompt called with:', JSON.stringify(prompt).substring(0, 100))
	      if (DEBUG) console.log('[AUTH] current stage:', state.loginStage)
      
	      if (lowerPrompt.includes('invalid password')) {
	        if (DEBUG) console.log('[AUTH] → invalid password error')
        commit('SET_LOGIN_ERROR', 'Invalid password')
        commit('SET_LOGGING_IN', false)
	      } else if (lowerPrompt.includes('new account')) {
	        if (DEBUG) console.log('[AUTH] → setting stage to password (new account)')
        commit('SET_LOGIN_STAGE', 'password')
	      } else if (lowerPrompt.includes('password')) {
	        if (DEBUG) console.log('[AUTH] → setting stage to password (existing account)')
        commit('SET_LOGIN_STAGE', 'password')
	      } else if (lowerPrompt.includes('character slot')) {
	        if (DEBUG) console.log('[AUTH] → setting stage to character (character slot)')
        commit('SET_LOGIN_STAGE', 'character')
	      } else if (lowerPrompt.includes('character') && lowerPrompt.includes('>')) {
	        if (DEBUG) console.log('[AUTH] → setting stage to character (character prompt)')
        commit('SET_LOGIN_STAGE', 'character')
	      } else if (lowerPrompt.includes('connected as')) {
	        if (DEBUG) console.log('[AUTH] → login complete, setting connected')
        commit('SET_LOGIN_STAGE', 'connected')
        commit('SET_LOGGING_IN', false)
        commit('game/CLEAR_MESSAGES', null, { root: true })
        commit('game/SET_PROMPT', '> ', { root: true })
	      } else {
	        if (DEBUG) console.log('[AUTH] → no match found, stage unchanged')
	      }
	
	      if (DEBUG) console.log('[AUTH] new stage:', state.loginStage)
      return state.loginStage
    },

    async selectCharacter({ commit }, slotName: string) {
      commit('SET_CHARACTER_SLOT', slotName)
      return { success: true }
    },

    async logout({ commit, dispatch }) {
      await dispatch('game/disconnect', null, { root: true })
      dispatch('popup/closePopup', null, { root: true })
      commit('RESET_AUTH')
      commit('game/RESET_STATE', null, { root: true })
    }
  },

	  getters: {
	    isAuthenticated: state => state.loginStage === 'connected'
	  }
}

export default auth