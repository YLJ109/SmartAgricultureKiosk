/* 当前语言：持久化到 localStorage；切换时同步 <html lang> 与民族文字字体 */

import { defineStore } from 'pinia'
import { I18N, LANG_CODES, LANG_FONTS, LANG_NATIVE, DEFAULT_FONT } from '../i18n'

const LS_KEY = 'ag_lang'

export const useLangStore = defineStore('lang', {
  state: () => ({ code: 'zh-CN' }),

  getters: {
    // 下拉选项：[{ code, native }]
    options: () => LANG_CODES.map((code) => ({ code, native: LANG_NATIVE[code] || code })),
  },

  actions: {
    init() {
      let saved = ''
      try {
        saved = localStorage.getItem(LS_KEY) || ''
      } catch (e) {
        saved = ''
      }
      this.code = I18N[saved] ? saved : 'zh-CN'
      this.apply()
    },

    setLang(code) {
      if (!I18N[code]) return
      this.code = code
      try {
        localStorage.setItem(LS_KEY, code)
      } catch (e) {
        /* 忽略存储失败 */
      }
      this.apply()
    },

    // 根节点上加字体回退链：维/哈、藏、蒙各自的字体链在 i18n 里定义
    apply() {
      const root = document.documentElement
      root.setAttribute('lang', this.code)
      root.style.setProperty('--k-font', LANG_FONTS[this.code] || DEFAULT_FONT)
    },

    // 取词条；缺词条时回退中文，再回退 key 本身
    t(key, params) {
      const pack = I18N[this.code] || I18N['zh-CN']
      let text = pack[key] !== undefined
        ? pack[key]
        : (I18N['zh-CN'][key] !== undefined ? I18N['zh-CN'][key] : key)
      if (params) {
        Object.keys(params).forEach((k) => {
          text = text.replace('{' + k + '}', params[k])
        })
      }
      return text
    },
  },
})
