<script setup>
/* 顶栏：品牌 + 语言下拉 + 呼叫工作人员 + 用户胶囊 + 退出 */
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import { useToast } from './useToast'
import { useLangStore } from '../stores/lang'
import { useUserStore } from '../stores/user'

const router = useRouter()
const lang = useLangStore()
const user = useUserStore()
const toast = useToast()

// 游客的名字不显示后端生成的「游客-XXXX」（那是硬编码中文，切语言不会变），
// 直接显示当前语言下的「游客」字样，做到"哪种语言就显示哪种语言"。
const nameText = computed(() =>
  user.isGuest ? lang.t('admin.role.guest') : user.displayName || '—',
)
const initial = computed(() => nameText.value.slice(0, 1))
const roleText = computed(() => lang.t('admin.role.' + user.roleLabel))

onMounted(() => {
  // 刷新后 token 还在但 profile 丢了，补拉一次，保证胶囊上显示姓名
  if (user.isLoggedIn && !user.profile) {
    user.fetchMe().catch(() => {
      /* 失败由全局 401 处理兜底，这里不打扰用户 */
    })
  }
})

function onLangChange(event) {
  lang.setLang(event.target.value)
}

function callHelp() {
  toast.info(lang.t('home.helpToast'))
}

function logout() {
  user.logout()
  router.replace({ name: 'login' })
}
</script>

<template>
  <header class="term-topbar">
    <button class="brand" type="button" @click="router.push('/')">
      <span class="brand-mark"><AppIcon name="leaf" /></span>
      <span class="brand-text">
        <span class="brand-name">{{ lang.t('brand.name') }}</span>
        <span class="brand-sub">{{ lang.t('brand.sub') }}</span>
      </span>
    </button>

    <div class="topbar-actions">
      <div class="lang-select-wrap">
        <AppIcon name="globe" />
        <select
          class="lang-select"
          :value="lang.code"
          :aria-label="lang.t('nav.home')"
          @change="onLangChange"
        >
          <option v-for="opt in lang.options" :key="opt.code" :value="opt.code">
            {{ opt.native }}
          </option>
        </select>
      </div>

      <button class="ag-btn ag-btn-help ag-btn-sm" type="button" @click="callHelp">
        <AppIcon name="user" />
        <span>{{ lang.t('home.help') }}</span>
      </button>

      <div class="user-chip">
        <span class="user-avatar">{{ initial }}</span>
        <span class="user-meta">
          <span class="user-name">{{ nameText }}</span>
          <!-- 游客的名字本身就是「游客」，再挂一行角色会重复，所以游客只显示一行 -->
          <span v-if="!user.isGuest" class="user-role">{{ roleText }}</span>
        </span>
      </div>

      <button class="ag-btn ag-btn-ghost ag-btn-sm" type="button" @click="logout">
        <AppIcon name="logout" />
        <span>{{ lang.t('nav.logout') }}</span>
      </button>
    </div>
  </header>
</template>
