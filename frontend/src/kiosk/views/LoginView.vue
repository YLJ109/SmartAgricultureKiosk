<script setup>
/* 登录页：登录 / 注册两个页签（姓名 + 手机号必填）；游客模式独立入口；6 语言下拉 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import { useToast } from '../components/useToast'
import { useLangStore } from '../stores/lang'
import { useUserStore } from '../stores/user'
import { api, errText } from '../api'

const router = useRouter()
const lang = useLangStore()
const user = useUserStore()
const toast = useToast()

// 手机号是账号主键，前端先按同一规则挡一遍，省一次往返；后端仍会再校验
const PHONE_RE = /^1[3-9]\d{9}$/

const tab = ref('login') // 'login' | 'register'
// 演示账号预填：方便直接点登录走通流程（账号已在数据库中注册）
const name = ref('艾力')
const phone = ref('13888888888')
const error = ref('')
const busy = ref(false)

function onLangChange(event) {
  lang.setLang(event.target.value)
}

function switchTab(next) {
  if (tab.value === next) return
  // 只切换模式，不清空已输入内容（老人重打一遍很费劲）；但要把上一次的错误提示清掉，
  // 否则登录失败留下的红字会一直挂到注册页上，误导用户。
  tab.value = next
  error.value = ''
}

// 两个页签共用同一套必填校验：姓名、手机号都必须合法
function validate() {
  if (!name.value.trim()) {
    error.value = lang.t('login.errName')
    return false
  }
  if (!PHONE_RE.test(phone.value.trim())) {
    error.value = lang.t('login.errPhone')
    return false
  }
  return true
}

async function run(request, skipValidate) {
  // 第二参数给游客用：validate() 是「注册/登录」的姓名+手机号必填校验，
  // 游客本来就不填这两项，若一并校验会把游客挡在门外（点了没反应）。
  if (busy.value) return
  if (!skipValidate && !validate()) return
  busy.value = true
  error.value = ''
  try {
    // 注册与登录都返回 TokenOut，拿到即可直接进首页
    const session = await request()
    user.setSession(session)
    router.replace({ name: 'home' })
  } catch (err) {
    // 按后端 code 取当前语言的文案（已注册 / 未注册 / 姓名不匹配…），
    // 没翻过的旧错误码再退回后端中文 message。
    // t() 内部依赖 this.code，不能裸传引用，故包一层箭头函数保住 this 绑定。
    error.value = errText(err, (k) => lang.t(k))
    toast.error(error.value)
  } finally {
    busy.value = false
  }
}

function submit() {
  if (tab.value === 'login') {
    // 手机号定位账号，姓名二次校验 —— 不匹配后端会拒绝，避免拿错别人的记录
    run(() => api.kioskLogin(name.value.trim(), phone.value.trim(), lang.code))
  } else {
    run(() => api.kioskRegister(name.value.trim(), phone.value.trim(), lang.code))
  }
}

function asGuest() {
  // 游客不填姓名不填手机号：记录不落库，历史与看板锁定（行为与改动前一致）
  // 跳过表单校验，否则空表单时会被必填提示拦住
  run(() => api.guest('', lang.code), true)
}
</script>

<template>
  <section class="login-body">
    <div class="login-bg" aria-hidden="true"></div>

    <div class="login-shell">
      <div class="login-hero">
        <div class="brand">
          <span class="brand-mark"><AppIcon name="leaf" /></span>
          <span class="brand-text">
            <span class="brand-name">{{ lang.t('brand.name') }}</span>
            <span class="brand-sub">{{ lang.t('brand.sub') }}</span>
          </span>
        </div>

        <h1>{{ lang.t('login.title') }}</h1>
        <p>{{ lang.t('login.desc') }}</p>

        <div class="hero-badges">
          <span class="hero-badge"><AppIcon name="scan" /><span>{{ lang.t('login.badge1') }}</span></span>
          <span class="hero-badge"><AppIcon name="globe" /><span>{{ lang.t('login.badge2') }}</span></span>
          <span class="hero-badge"><AppIcon name="shield" /><span>{{ lang.t('login.badge3') }}</span></span>
        </div>
      </div>

      <div class="login-card">
        <h2>{{ lang.t('login.cardTitle') }}</h2>
        <p class="hint">{{ lang.t('login.cardHint') }}</p>

        <!-- 语言选择放在说明之后：先把"这是干什么的"讲清楚，再让用户挑语言。
             对听不懂中文的老人来说，这两行是唯一的入口提示，不能压在选语言控件下面。 -->
        <div class="lang-select-wrap">
          <AppIcon name="globe" />
          <select class="lang-select" :value="lang.code" @change="onLangChange">
            <option v-for="opt in lang.options" :key="opt.code" :value="opt.code">
              {{ opt.native }}
            </option>
          </select>
        </div>

        <div class="seg login-tabs">
          <button type="button" :class="{ on: tab === 'login' }" @click="switchTab('login')">
            {{ lang.t('login.tabLogin') }}
          </button>
          <button type="button" :class="{ on: tab === 'register' }" @click="switchTab('register')">
            {{ lang.t('login.tabRegister') }}
          </button>
        </div>

        <div class="field">
          <label>
            <span>{{ lang.t('login.name') }}</span><span class="req">*</span>
          </label>
          <input
            v-model="name"
            type="text"
            maxlength="20"
            autocomplete="name"
            :placeholder="lang.t('login.namePh')"
            @keydown.enter.prevent="submit"
          />
        </div>

        <div class="field">
          <label>
            <span>{{ lang.t('login.phone') }}</span><span class="req">*</span>
          </label>
          <input
            v-model="phone"
            type="tel"
            inputmode="numeric"
            maxlength="11"
            autocomplete="tel"
            :placeholder="lang.t('login.phonePh')"
            @keydown.enter.prevent="submit"
          />
        </div>

        <p v-if="error" class="login-error">{{ error }}</p>

        <button class="ag-btn ag-btn-primary" type="button" :disabled="busy" @click="submit">
          <AppIcon name="check" />
          <span>{{ tab === 'login' ? lang.t('login.submit') : lang.t('login.register') }}</span>
        </button>

        <div class="login-divider"><span>{{ lang.t('login.or') }}</span></div>

        <button class="ag-btn ag-btn-ghost" type="button" :disabled="busy" @click="asGuest">
          <AppIcon name="user" />
          <span>{{ lang.t('login.guest') }}</span>
        </button>
      </div>
    </div>
  </section>
</template>
