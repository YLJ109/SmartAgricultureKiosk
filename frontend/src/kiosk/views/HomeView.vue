<script setup>
/* 首页：四个大功能卡铺满整屏（与 demo 一致，不放标题块，把高度全留给功能卡） */
import { useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import { useLangStore } from '../stores/lang'
import { useUserStore } from '../stores/user'
import { useToast } from '../components/useToast'

const router = useRouter()
const lang = useLangStore()
const user = useUserStore()
const toast = useToast()

// guestLocked：游客模式下不可进入。
// 历史记录与数据看板都建立在"可追溯的用户身份"上，游客没有身份，进去也只会是空列表。
const cards = [
  { key: 'detect', icon: 'scan', color: 'fc-green', to: '/detect' },
  { key: 'chat', icon: 'chat', color: 'fc-blue', to: '/chat' },
  { key: 'history', icon: 'history', color: 'fc-amber', to: '/history', guestLocked: true },
  { key: 'board', icon: 'chart', color: 'fc-violet', to: '/board', guestLocked: true },
]

const isLocked = (card) => !!card.guestLocked && user.isGuest

function open(card) {
  if (isLocked(card)) {
    // 不静默失败：明确告诉游客为什么进不去、下一步该做什么
    toast.info(lang.t('home.guestLocked'))
    return
  }
  router.push(card.to)
}
</script>

<template>
  <section class="view">
    <div class="feature-grid">
      <button
        v-for="card in cards"
        :key="card.key"
        class="feature-card"
        :class="[card.color, { 'is-locked': isLocked(card) }]"
        type="button"
        @click="open(card)"
      >
        <AppIcon class="feature-icon" :name="card.icon" />
        <span class="feature-text">
          <span class="feature-title">{{ lang.t('card.' + card.key + '.t') }}</span>
          <span class="feature-desc">{{ lang.t('card.' + card.key + '.d') }}</span>
        </span>

        <!-- 上锁的卡片换掉入口按钮，避免"点了没反应"这种最让人困惑的状态 -->
        <span v-if="isLocked(card)" class="feature-go is-locked-go">
          <AppIcon name="lock" />
          <span>{{ lang.t('home.locked') }}</span>
        </span>
        <span v-else class="feature-go">
          <span>{{ lang.t('card.enter') }}</span>
          <AppIcon name="arrowRight" />
        </span>
      </button>
    </div>
  </section>
</template>
