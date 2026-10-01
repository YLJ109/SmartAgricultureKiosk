/* 路由：除登录页外都需要登录态；游客被挡在历史记录与数据看板之外 */

import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '../api'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  { path: '/', name: 'home', component: () => import('../views/HomeView.vue') },
  { path: '/detect', name: 'detect', component: () => import('../views/DetectView.vue') },
  { path: '/chat', name: 'chat', component: () => import('../views/ChatView.vue') },
  { path: '/history', name: 'history', component: () => import('../views/HistoryView.vue') },
  { path: '/board', name: 'board', component: () => import('../views/BoardView.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

// 游客不可进入的页面：记录与统计都依赖可追溯的用户身份
const GUEST_BLOCKED = new Set(['history', 'board'])

/**
 * 从 JWT 载荷里直接读 role。
 * 这样路由守卫不必为了拿角色再打一次 /auth/me —— 刷新页面时守卫是同步跑的，
 * 发请求会拖慢首屏，而且接口没回来之前根本没法判权限。
 */
function roleFromToken() {
  const token = getToken()
  if (!token) return ''
  try {
    const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
    return JSON.parse(new TextDecoder('utf-8').decode(bytes)).role || ''
  } catch (e) {
    return ''
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const authed = !!getToken()
  if (to.name !== 'login' && !authed) return { name: 'login' }
  if (to.name === 'login' && authed) return { name: 'home' }
  if (GUEST_BLOCKED.has(to.name) && roleFromToken() === 'guest') return { name: 'home' }
  return true
})

export default router
