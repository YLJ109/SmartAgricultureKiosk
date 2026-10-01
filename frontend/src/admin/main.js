/**
 * 管理后台入口（admin.html → #admin）。
 *
 * Element Plus 刻意用完整引入：后台是独立 chunk，不会拖慢终端端首屏，
 * 优先保证"打开就能用、不漏组件"，不为此承担按需引入的配置风险。
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import 'element-plus/dist/index.css'
import '@admin/styles/admin.css'

import App from '@admin/App.vue'
import router from '@admin/router'

const app = createApp(App)

app.use(createPinia())
app.use(router)
// locale 交给 Element Plus 全局配置，分页器/日期选择器等内置文案才是中文
app.use(ElementPlus, { locale: zhCn })

// 全量注册图标，模板里可直接用 <DataLine /> 这类写法
for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component)
}

app.mount('#admin')
