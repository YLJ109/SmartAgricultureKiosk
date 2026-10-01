<script setup>
/* 应用外壳：登录页整屏独占；其余页面 = 顶栏 + 主区 + 全局 Toast */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import KTopbar from './components/KTopbar.vue'
import KToast from './components/KToast.vue'

const route = useRoute()
const isLogin = computed(() => route.name === 'login')
</script>

<template>
  <KTopbar v-if="!isLogin" />
  <main v-if="!isLogin" class="term-main">
    <router-view />
  </main>
  <router-view v-else />
  <KToast />
</template>
