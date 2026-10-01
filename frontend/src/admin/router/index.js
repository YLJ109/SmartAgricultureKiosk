/**
 * 后台路由。
 *
 * 用 hash 模式（createWebHashHistory）而不是 history：本项目是 vite 多页应用，
 * admin.html 与 index.html 是两个入口，history 模式下 /login 这类深链接会被
 * dev/preview 服务器回退到 index.html（终端端），导致刷新后台页面跳到终端。
 * hash 模式（admin.html#/login）不依赖服务器回退，最稳。
 */
import { createRouter, createWebHashHistory } from 'vue-router'
import { getToken } from '@admin/api'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@admin/views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('@admin/layouts/AdminLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@admin/views/DashboardView.vue'),
        meta: { title: '数据看板' },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('@admin/views/UsersView.vue'),
        meta: { title: '用户管理' },
      },
      {
        path: 'providers',
        name: 'providers',
        component: () => import('@admin/views/ProvidersView.vue'),
        meta: { title: 'AI 配置' },
      },
      {
        path: 'lang-resources',
        name: 'lang-resources',
        component: () => import('@admin/views/LangResourceView.vue'),
        meta: { title: '多语言资源' },
      },
      {
        path: 'logs',
        name: 'logs',
        component: () => import('@admin/views/LogsView.vue'),
        meta: { title: '操作日志' },
      },
    ],
  },
  // 兜底：未知路径回看板，避免出现空白页
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 登录守卫：非公开页面必须带 token，并把原目标塞进 query 以便登录后跳回
router.beforeEach((to) => {
  const logged = Boolean(getToken())
  if (!to.meta.public && !logged) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && logged) {
    return { path: '/dashboard' }
  }
  return true
})

export default router
