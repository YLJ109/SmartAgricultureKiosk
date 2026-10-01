<script setup>
/**
 * 后台主框架：左侧可折叠菜单 + 顶栏（面包屑 / 用户 / 退出）+ 内容区。
 * 登录态在这里兜一次底（刷新页面后 store 为空），避免子页面各自处理。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataLine, User, Setting, Collection, Document, Fold, Expand, SwitchButton } from '@element-plus/icons-vue'
import { useUserStore } from '@admin/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const collapsed = ref(false)

const ROLE_LABEL = { farmer: '农户', guest: '游客', operator: '农技员', admin: '管理员' }

const menus = [
  { path: '/dashboard', title: '数据看板', icon: DataLine },
  { path: '/users', title: '用户管理', icon: User },
  { path: '/providers', title: 'AI 配置', icon: Setting },
  { path: '/lang-resources', title: '多语言资源', icon: Collection },
  { path: '/logs', title: '操作日志', icon: Document },
]

// el-menu 的高亮项用路径匹配，子路由（当前没有二级）也能正确高亮
const activeMenu = computed(() => route.path)
const breadcrumbs = computed(() => {
  const title = route.meta?.title
  return title && title !== '登录' ? ['管理后台', title] : ['管理后台']
})

const displayName = computed(() => userStore.user?.display_name || userStore.user?.username || '未登录')
const roleLabel = computed(() => ROLE_LABEL[userStore.user?.role] || userStore.user?.role || '')
const avatarText = computed(() => (displayName.value || 'U').slice(0, 1))

async function onLogout() {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '退出确认', {
      confirmButtonText: '退出',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return // 用户点了取消
  }
  userStore.logout()
  ElMessage.success('已退出登录')
  router.replace('/login')
}

onMounted(() => {
  // token 有效但刷新丢内存时补拉用户信息；失败交给 axios 拦截器统一处理
  userStore.ensureUser().catch(() => {})
})
</script>

<template>
  <el-container class="admin-shell">
    <el-aside :width="collapsed ? '64px' : '210px'" class="admin-aside">
      <div class="brand" :class="{ collapsed }">
        <span class="brand-mark">农</span>
        <span v-show="!collapsed" class="brand-text">智慧农业后台</span>
      </div>

      <el-menu :default-active="activeMenu" :collapse="collapsed" :collapse-transition="false" router class="admin-menu">
        <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
          <el-icon><component :is="m.icon" /></el-icon>
          <template #title>{{ m.title }}</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="admin-header">
        <div class="header-left">
          <el-icon class="collapse-btn" @click="collapsed = !collapsed">
            <Expand v-if="collapsed" />
            <Fold v-else />
          </el-icon>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item v-for="item in breadcrumbs" :key="item">{{ item }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="header-right">
          <el-dropdown trigger="click" @command="onLogout">
            <span class="user-chip">
              <el-avatar :size="28" class="user-avatar">{{ avatarText }}</el-avatar>
              <span class="user-name">{{ displayName }}</span>
              <el-tag v-if="roleLabel" size="small" type="success" effect="plain">{{ roleLabel }}</el-tag>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">
                  <el-icon><SwitchButton /></el-icon>
                  退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="admin-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.admin-shell {
  height: 100vh;
}

/* ---------- 侧栏 ---------- */
.admin-aside {
  background: #10231a;
  transition: width 0.2s ease;
  overflow: hidden;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 56px;
  padding: 0 16px;
  color: #fff;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  white-space: nowrap;
}

.brand.collapsed {
  justify-content: center;
  padding: 0;
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: #2e9e4f;
  font-weight: 700;
  font-size: 14px;
  flex: none;
}

.brand-text {
  font-size: 15px;
  font-weight: 600;
}

.admin-menu {
  border-right: none;
  background: transparent;
  --el-menu-bg-color: transparent;
  --el-menu-text-color: #c3d0c9;
  --el-menu-hover-bg-color: rgba(46, 158, 79, 0.16);
  --el-menu-active-color: #ffffff;
}

.admin-menu :deep(.el-menu-item.is-active) {
  background: #2e9e4f;
  color: #fff;
}

.admin-menu :deep(.el-menu-item) {
  margin: 4px 8px;
  border-radius: 6px;
  height: 44px;
}

/* ---------- 顶栏 ---------- */
.admin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  background: #fff;
  border-bottom: 1px solid var(--admin-border);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.collapse-btn {
  font-size: 18px;
  cursor: pointer;
  color: var(--admin-text-weak);
}

.collapse-btn:hover {
  color: var(--admin-primary);
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  outline: none;
}

.user-chip:hover {
  background: #f3f5f7;
}

.user-avatar {
  background: var(--admin-primary);
  color: #fff;
  font-size: 13px;
}

.user-name {
  font-size: 14px;
  color: var(--admin-text);
}

/* ---------- 内容区 ---------- */
.admin-main {
  padding: 0;
  background: var(--admin-bg);
  overflow-y: auto;
}
</style>
