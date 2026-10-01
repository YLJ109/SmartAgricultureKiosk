/* ==========================================================================
   接口层：axios 实例 + 终端端用到的全部接口封装
   - baseURL 用相对路径 '/api'，开发态走 vite 代理到后端
   - 请求拦截器统一加 Bearer token；401 交给外部处理器（跳登录页）
   - 响应拦截器把后端的 {code,message,detail} 归一化成带 code / userMessage 的 Error
   ========================================================================== */

import axios from 'axios'

const TOKEN_KEY = 'ag_token'

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch (e) {
    return ''
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch (e) {
    /* localStorage 不可用时静默降级 */
  }
}

// 由 main.js 注册：token 失效时清会话并回登录页，避免 api 层反向依赖 router 造成循环引用
let unauthorizedHandler = null
export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = fn
}

const http = axios.create({ baseURL: '/api', timeout: 60000 })

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const response = error.response
    const status = response && response.status
    const data = response && response.data
    if (status === 401 && unauthorizedHandler) unauthorizedHandler()

    // 后端 message 是可直接展示给用户的中文文案；网络层失败则留空交给视图兜底
    const message = (data && data.message) || ''
    const wrapped = new Error(message || 'request failed')
    wrapped.status = status
    // 同时保留后端机器可读的 code：6 语言界面靠它取本地化文案。
    // 网络层异常（连不上后端）拿不到 data，兜个 'unknown' 让视图走通用文案。
    wrapped.code = (data && data.code) || 'unknown'
    wrapped.userMessage = message
    return Promise.reject(wrapped)
  },
)

/**
 * 按错误码取本地化文案；没有对应词条时回退后端 message，再回退通用兜底文案。
 *
 * 为什么用 `localized !== key` 判断词条是否存在：
 * lang store 的 t() 在缺词条时会静默逐级回退（当前语言 → 中文 → key 本身），
 * 所以"取到了值"并不代表当前语言真的翻过这条。只有当返回值与传入的 key 不同，
 * 才能确定这个词条真的存在，此时才用它；否则说明没翻过，退回后端中文 message。
 */
export function errText(err, t) {
  const code = err && err.code ? String(err.code) : ''
  if (code) {
    const key = 'err.' + code
    const localized = t(key)
    if (localized && localized !== key) return localized
  }
  return (err && err.userMessage) || t('common.error')
}

export const api = {
  // ---- 认证 ----
  login: (username, password) => http.post('/auth/login', { username, password }),
  // 一体机走注册/登录两条接口：手机号是账号主键，姓名做二次校验（详见后端 auth.py）
  kioskRegister: (displayName, phone, lang) =>
    http.post('/auth/kiosk/register', { display_name: displayName, phone, lang }),
  kioskLogin: (displayName, phone, lang) =>
    http.post('/auth/kiosk/login', { display_name: displayName, phone, lang }),
  // 不填姓名 → 游客（不落库，历史与看板上锁）
  guest: (displayName, lang) => http.post('/auth/guest', { display_name: displayName, lang }),
  me: () => http.get('/auth/me'),

  // ---- 系统 ----
  systemInfo: () => http.get('/system/info'),
  systemLangs: () => http.get('/system/langs'),
  systemClasses: (lang) => http.get('/system/classes', { params: { lang } }),
  systemCalendar: (lang) => http.get('/system/calendar', { params: { lang } }),

  // ---- 识别 ----
  samples: (lang) => http.get('/recognize/samples', { params: { lang } }),
  recognize: (file, { lang, crop = '', channel = 'local' } = {}) => {
    const form = new FormData()
    form.append('file', file)
    form.append('lang', lang)
    form.append('crop', crop)
    form.append('channel', channel)
    // 不手动设置 Content-Type，交给 axios 自动带 multipart boundary
    return http.post('/recognize', form)
  },

  // ---- 农事问答 ----
  chatAsk: (question, lang) => http.post('/chat/ask', { question, lang }),
  chatQuicks: (lang) => http.get('/chat/quicks', { params: { lang } }),

  // ---- 历史记录 ----
  history: (params) => http.get('/history', { params }),
  historyChats: (params) => http.get('/history/chats', { params }),
  historyDetail: (recordNo, lang) =>
    http.get(`/history/${encodeURIComponent(recordNo)}`, { params: { lang } }),
  historyDelete: (recordNo) => http.delete(`/history/${encodeURIComponent(recordNo)}`),

  // ---- 数据看板 ----
  // 终端端只展示"我自己的"数据；全站统计接口保留给管理后台使用
  statsMine: (lang, days = 7) => http.get('/stats/mine', { params: { lang, days } }),
}

export default api
