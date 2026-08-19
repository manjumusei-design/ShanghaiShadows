import { createStore } from 'vuex'
import game from './modules/game'
import auth from './modules/auth'
import ui from './modules/ui'
import popup from './modules/popup'

export default createStore({
  modules: {
    game,
    auth,
    ui,
    popup
  },
  strict: import.meta.env.MODE !== 'production'
})
