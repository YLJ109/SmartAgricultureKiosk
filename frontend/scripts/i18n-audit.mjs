/**
 * 多语言词条覆盖审计
 *
 * 为什么需要它：`t()` 在缺词条时会静默回退中文（见 stores/lang.js），
 * 所以"漏翻"不会报错、不会白屏，只会悄悄显示中文 —— 光看代码根本发现不了。
 * 这个脚本把差异列出来。
 *
 * 用法：
 *   node scripts/i18n-audit.mjs          # 列出缺失词条
 *   node scripts/i18n-audit.mjs --json   # 只输出 JSON，便于接 CI
 *
 * 退出码：有缺失则 1，全齐则 0（可直接用作 CI 门禁）。
 */

import { I18N, LANG_CODES } from '../src/kiosk/i18n/index.js'

const BASE = 'zh-CN'
const asJson = process.argv.includes('--json')

const baseKeys = Object.keys(I18N[BASE])
const report = {}

for (const code of LANG_CODES) {
  if (code === BASE) continue
  const pack = I18N[code] || {}
  const missing = baseKeys.filter((k) => {
    const v = pack[k]
    return v === undefined || v === null || String(v).trim() === ''
  })
  // 词条内容与中文一模一样 => 基本可以断定是漏翻（专有名词除外，单独看）
  const sameAsBase = baseKeys.filter((k) => pack[k] !== undefined && String(pack[k]) === String(I18N[BASE][k]))
  report[code] = { 缺失: missing, 与中文相同: sameAsBase }
}

const totalMissing = Object.values(report).reduce((n, r) => n + r.缺失.length, 0)
const totalSame = Object.values(report).reduce((n, r) => n + r.与中文相同.length, 0)

if (asJson) {
  console.log(JSON.stringify({ baseKeys: baseKeys.length, report }, null, 2))
} else {
  console.log(`基准语言 ${BASE} 共 ${baseKeys.length} 条词条\n`)
  for (const code of LANG_CODES) {
    if (code === BASE) continue
    const r = report[code]
    const status = r.缺失.length === 0 ? 'OK  ' : '缺失'
    console.log(`[${status}] ${code}  缺失 ${r.缺失.length} 条，与中文相同 ${r.与中文相同.length} 条`)
    if (r.缺失.length) {
      console.log('        ' + r.缺失.join(', '))
    }
  }
  console.log(`\n合计缺失 ${totalMissing} 条，与中文相同 ${totalSame} 条`)
  if (totalMissing === 0) console.log('各语言词条已齐。')
}

process.exit(totalMissing > 0 ? 1 : 0)
