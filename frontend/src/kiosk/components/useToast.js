/* Toast 全局单例：模块级 reactive 数组，任何组件 import 后都是同一份状态 */

import { reactive } from 'vue'

export const toasts = reactive([])

let seq = 0

export function useToast() {
  function show(message, type = 'success', duration = 2200) {
    if (!message) return
    const id = ++seq
    toasts.push({ id, message, type })
    setTimeout(() => {
      const index = toasts.findIndex((t) => t.id === id)
      if (index > -1) toasts.splice(index, 1)
    }, duration)
  }

  return {
    show,
    info: (message) => show(message, 'success'),
    error: (message) => show(message, 'error'),
  }
}
