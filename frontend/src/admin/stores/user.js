/**
 * 后台登录态。只保存 token 与当前用户，不做持久化用户信息——
 * 用户资料每次进后台用 /auth/me 拉一次，避免本地缓存与后端不一致。
 */
import { ref } from 'vue'
import { defineStore } from 'pinia'
import { authApi, clearToken, getToken, setToken } from '@admin/api'

export const useUserStore = defineStore('adminUser', () => {
  const token = ref(getToken())
  const user = ref(null)

  async function login(username, password) {
    const data = await authApi.login({ username, password })
    token.value = data.access_token
    setToken(data.access_token)
    user.value = data.user
    return data.user
  }

  async function fetchMe() {
    user.value = await authApi.me()
    return user.value
  }

  // 刷新页面后 store 内存为空，但 token 还在，需要补拉一次用户信息
  async function ensureUser() {
    if (!user.value && token.value) await fetchMe()
    return user.value
  }

  function logout() {
    token.value = ''
    user.value = null
    clearToken()
  }

  return { token, user, login, fetchMe, ensureUser, logout }
})
