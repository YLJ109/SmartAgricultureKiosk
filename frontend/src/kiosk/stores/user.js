/* 用户与 token：token 放 localStorage，刷新后仍可复用会话 */

import { defineStore } from 'pinia'
import { api, getToken, setToken } from '../api'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: getToken(),
    profile: null,
  }),

  getters: {
    isLoggedIn: (state) => !!state.token,
    // 游客：能看能问，但不留痕，也进不了历史记录与数据看板
    isGuest: (state) => !!(state.profile && state.profile.role === 'guest'),
    displayName: (state) => (state.profile && state.profile.display_name) || '',
    roleLabel: (state) => (state.profile && state.profile.role) || 'guest',
  },

  actions: {
    // 登录 / 游客模式返回的都是 TokenOut，统一落到这里
    setSession(payload) {
      this.token = payload.access_token
      setToken(payload.access_token)
      this.profile = payload.user || null
    },

    async fetchMe() {
      this.profile = await api.me()
      return this.profile
    },

    logout() {
      this.token = ''
      this.profile = null
      setToken('')
    },
  },
})
