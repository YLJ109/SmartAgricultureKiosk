/**
 * 后台统一的 HTTP 层。
 *
 * 为什么 token 用 localStorage 而不是内存：后台是"运营工具"，农技员刷新页面
 * 不该被迫重新登录；localStorage 在这个独立 chunk 里没有终端端共享的顾虑。
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'

const TOKEN_KEY = 'admin_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

const http = axios.create({
  baseURL: '/api',
  timeout: 20000,
})

// 请求：注入 Bearer token
http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应：统一解包 data；401 清登录态并回登录页
http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status
    const url = error.config?.url || ''
    const message = error.response?.data?.message || error.message || '网络异常，请稍后重试'
    // 登录接口的失败由页面自己提示（要区分"账号密码错"和"网络错"），不在这里弹
    const isLogin = url.includes('/auth/login')

    if (status === 401 && !isLogin) {
      clearToken()
      ElMessage.error(message || '登录已过期，请重新登录')
      // 路由用 hash 模式，直接改 hash 即可触发跳转，避免 api 反向依赖 router 造成循环引用
      if (window.location.hash !== '#/login') window.location.hash = '#/login'
    } else if (!isLogin) {
      ElMessage.error(message)
    }

    return Promise.reject(error)
  },
)

// ---------- 认证 ----------
export const authApi = {
  login: (data) => http.post('/auth/login', data),
  me: () => http.get('/auth/me'),
}

// ---------- 看板 ----------
export const dashboardApi = {
  dashboard: () => http.get('/admin/dashboard'),
  trend: (days = 30) => http.get('/stats/trend', { params: { days } }),
  diseaseDist: (limit = 8, lang = 'zh-CN') => http.get('/stats/disease-dist', { params: { limit, lang } }),
  regions: (limit = 8) => http.get('/stats/regions', { params: { limit } }),
  topQuestions: (limit = 8) => http.get('/stats/top-questions', { params: { limit } }),
}

// ---------- 用户管理 ----------
export const userApi = {
  list: (params) => http.get('/admin/users', { params }),
  create: (data) => http.post('/admin/users', data),
  update: (id, data) => http.patch(`/admin/users/${id}`, data),
  remove: (id) => http.delete(`/admin/users/${id}`),
}

// ---------- 大模型厂商 ----------
export const providerApi = {
  list: () => http.get('/admin/providers'),
  create: (data) => http.post('/admin/providers', data),
  update: (provider, data) => http.patch(`/admin/providers/${provider}`, data),
  remove: (provider) => http.delete(`/admin/providers/${provider}`),
  test: (provider) => http.post(`/admin/providers/${provider}/test`),
}

// ---------- 多语言资源 ----------
export const langApi = {
  list: (params) => http.get('/admin/lang-resources', { params }),
  upsert: (data) => http.put('/admin/lang-resources', data),
  remove: (id) => http.delete(`/admin/lang-resources/${id}`),
}

// ---------- 操作日志 ----------
export const logApi = {
  list: (params) => http.get('/admin/logs', { params }),
}
