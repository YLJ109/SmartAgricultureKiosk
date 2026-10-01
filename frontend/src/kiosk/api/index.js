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
  /** 扫码上传：开一次性会话，返回二维码里要放的手机上传页地址 */
  mobileSession: () => http.post('/recognize/mobile/session'),
  /** 扫码上传：轮询手机是否已传图；ready 为真时 image_url 就是取回的图片 */
  mobilePending: (token) => http.get('/recognize/mobile/pending', { params: { token } }),
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

  /**
   * 流式问答：每收到一块就回调 onDelta(text)，结束时回调 onMeta(meta)。
   *
   * 为什么绕开 axios 用原生 fetch：
   *   - axios 底层的 XHR 拿不到增量响应体，只能等整段收完（一体机上是 9 秒白屏）；
   *   - EventSource 只能发 GET，带不了 Authorization 头和请求体；
   * 所以这里手工读 ReadableStream，按 SSE 帧边界切分。
   */
  chatStream: async (question, lang, { onDelta, onMeta } = {}) => {
    const token = getToken()
    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ question, lang }),
    })

    if (!resp.ok) {
      // 与 axios 拦截器保持同一套错误形状，视图层才能用同一个 errText 取本地化文案
      let message = ''
      try {
        message = ((await resp.json()) || {}).message || ''
      } catch (e) {
        /* 非 JSON 错误体（如网关返回的 HTML）走兜底文案 */
      }
      const wrapped = new Error(message || 'request failed')
      wrapped.status = resp.status
      wrapped.userMessage = message
      wrapped.code = 'unknown'
      if (resp.status === 401 && unauthorizedHandler) unauthorizedHandler()
      throw wrapped
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let cut
      while ((cut = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, cut).trim()
        buf = buf.slice(cut + 1)
        if (!line.startsWith('data:')) continue // 空行与心跳注释行直接跳过
        const body = line.slice(5).trim()
        if (!body || body === '[DONE]') continue
        let evt
        try {
          evt = JSON.parse(body)
        } catch (e) {
          continue // 半截帧，等下一轮 buffer 拼完整
        }
        if (evt.type === 'delta') {
          if (onDelta) onDelta(evt.text || '')
        } else if (evt.type === 'meta') {
          if (onMeta) onMeta(evt)
        }
      }
    }
  },

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
