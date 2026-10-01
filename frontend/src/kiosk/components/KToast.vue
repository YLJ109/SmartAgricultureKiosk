<script setup>
/* 全局 Toast 容器：挂一次在 App.vue 里即可 */
import AppIcon from './AppIcon.vue'
import { toasts } from './useToast'
</script>

<template>
  <div class="toast-host" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="item in toasts" :key="item.id" class="toast" :class="'toast-' + item.type">
        <AppIcon :name="item.type === 'error' ? 'alert' : 'check'" />
        <span>{{ item.message }}</span>
      </div>
    </TransitionGroup>
  </div>
</template>
