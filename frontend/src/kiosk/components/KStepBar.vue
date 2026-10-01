<script setup>
/* 三步流程条：① 拍照选图 → ② 查看结果 → ③ 按建议处理 */
defineProps({
  current: { type: Number, default: 1 },
  steps: { type: Array, default: () => [] },
})
</script>

<template>
  <div class="step-bar">
    <div
      v-for="(label, index) in steps"
      :key="index"
      class="step-item"
      :class="{ 'is-active': index + 1 === current, 'is-done': index + 1 < current }"
    >
      <span class="step-no">{{ index + 1 }}</span>
      <span>{{ label }}</span>
    </div>
  </div>
</template>
