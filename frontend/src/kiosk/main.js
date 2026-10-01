/* 终端端入口：创建 app、装配 pinia/router/全局样式 */

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { setUnauthorizedHandler, setToken } from './api'
import { useLangStore } from './stores/lang'
import { useUserStore } from './stores/user'

import './styles/tokens.css'
import './styles/kiosk.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)

// 语言在挂载前就位，避免首帧用错字体与文案
const lang = useLangStore(pinia)
lang.init()

// 401 统一处理：清会话 + 回登录页（注册在这里，避免 api 层反向依赖 router）
setUnauthorizedHandler(() => {
  setToken('')
  const user = useUserStore(pinia)
  user.token = ''
  user.profile = null
  if (router.currentRoute.value.name !== 'login') {
    router.replace({ name: 'login' })
  }
})

app.use(router)
app.mount('#kiosk')
