<script setup>
/* 个人数据看板：只展示当前登录农户自己的记录（累计/今日检测、问答次数、
   最常见问题、问题类型分布、最近 7 天趋势）。图表仍是手写 SVG + CSS，不引图表库，
   与终端端其余页面保持一致。 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import { useLangStore } from '../stores/lang'
import { CATEGORY_KEY } from '../i18n'
import { api } from '../api'

const router = useRouter()
const lang = useLangStore()

const mine = ref(null)

// 固定色板：同一大类刷新 / 切语言都不换色，方便用户形成记忆
const CAT_COLORS = {
  disease: '#d93025',
  pest: '#e59500',
  nutrient: '#1a73e8',
  phyto: '#6b46c1',
  healthy: '#2e9e4f',
  unknown: '#8b9491',
}

const detectionTotal = computed(() => (mine.value ? mine.value.detection_total : 0))
const todayTotal = computed(() => (mine.value ? mine.value.today_total : 0))
const chatTotal = computed(() => (mine.value ? mine.value.chat_total : 0))
const topIssues = computed(() => (mine.value && mine.value.top_issues) || [])
const categoryDist = computed(() => (mine.value && mine.value.category_dist) || [])
const trend = computed(() => (mine.value && mine.value.trend) || [])

// KPI：最常见的问题。没有记录时留占位符，避免出现空白框
const topIssueName = computed(() => (topIssues.value.length ? topIssues.value[0].name : ''))

const issueMax = computed(() => Math.max(1, ...topIssues.value.map((i) => i.count)))

// 大类分布：category 是机器可读枚举，展示前先过一层 i18n
const distSegs = computed(() =>
  categoryDist.value.map((d) => ({
    key: d.category,
    name: lang.t(CATEGORY_KEY[d.category] || 'cat.unknown'),
    value: d.count,
    color: CAT_COLORS[d.category] || '#8b9491',
  })),
)

const distTotal = computed(() => categoryDist.value.reduce((sum, d) => sum + d.count, 0))

const donutArcs = computed(() => {
  const total = distTotal.value
  if (!total) return []
  const R = 54
  const C = 2 * Math.PI * R
  let offset = 0
  return distSegs.value.map((seg) => {
    const len = (seg.value / total) * C
    const arc = {
      key: seg.key,
      color: seg.color,
      dash: `${len.toFixed(2)} ${(C - len).toFixed(2)}`,
      offset: (-offset).toFixed(2),
    }
    offset += len
    return arc
  })
})

const trendMax = computed(() => Math.max(1, ...trend.value.map((p) => p.value)))
const hasTrend = computed(() => trend.value.some((p) => p.value > 0))

// 7 根柱子也要留出标签位；超过 6 根时抽稀，避免文字互相覆盖
const labelStep = computed(() => Math.max(1, Math.ceil(trend.value.length / 6)))

function fmt(value) {
  if (value === undefined || value === null) return '—'
  return Number(value).toLocaleString(lang.code)
}

async function load() {
  try {
    mine.value = await api.statsMine(lang.code, 7)
  } catch (e) {
    // 取数失败时退回全 0，让空状态兜底，不把页面卡在报错上
    mine.value = null
  }
}

onMounted(load)
watch(() => lang.code, load)
</script>

<template>
  <section class="view">
    <div class="page-head">
      <button class="ag-btn ag-btn-ghost" type="button" @click="router.push('/')">
        <AppIcon name="arrowRight" style="transform: rotate(180deg)" />
        <span>{{ lang.t('nav.back') }}</span>
      </button>
      <div class="page-head-main">
        <span class="page-title">{{ lang.t('board.title') }}</span>
        <span class="page-sub">{{ lang.t('board.sub') }}</span>
      </div>
    </div>

    <div class="kpi-strip">
      <div class="kpi">
        <AppIcon class="kpi-icon" name="scan" />
        <span class="kpi-label">{{ lang.t('stat.total') }}</span>
        <span class="kpi-value">{{ fmt(detectionTotal) }}</span>
      </div>
      <div class="kpi">
        <AppIcon class="kpi-icon" name="sun" />
        <span class="kpi-label">{{ lang.t('stat.today') }}</span>
        <span class="kpi-value">{{ fmt(todayTotal) }}</span>
      </div>
      <div class="kpi">
        <AppIcon class="kpi-icon" name="chat" />
        <span class="kpi-label">{{ lang.t('stat.qa') }}</span>
        <span class="kpi-value">{{ fmt(chatTotal) }}</span>
      </div>
      <div class="kpi">
        <AppIcon class="kpi-icon" name="shield" />
        <span class="kpi-label">{{ lang.t('board.issueTop') }}</span>
        <span class="kpi-value kpi-value--text" :title="topIssueName">{{ topIssueName || '—' }}</span>
      </div>
    </div>

    <div class="board-grid">
      <!-- 图 1：最常见问题 TOP 5（横向条形，纯 CSS） -->
      <div class="panel">
        <div class="panel-head"><AppIcon name="trend" /><h3>{{ lang.t('board.topIssues') }}</h3></div>
        <div v-if="topIssues.length" class="issue-list">
          <div v-for="(item, i) in topIssues" :key="item.code" class="issue-row">
            <span class="issue-no">{{ i + 1 }}</span>
            <span class="issue-name" :title="item.name">{{ item.name }}</span>
            <span class="issue-bar">
              <span :style="{ width: Math.max(4, (item.count / issueMax) * 100) + '%' }"></span>
            </span>
            <span class="issue-count">{{ fmt(item.count) }}</span>
          </div>
        </div>
        <p v-else class="board-empty">{{ lang.t('board.emptyDetect') }}</p>
      </div>

      <!-- 图 2：问题类型分布（环形，沿用原有 donut 写法） -->
      <div class="panel">
        <div class="panel-head"><AppIcon name="chart" /><h3>{{ lang.t('board.typeDist') }}</h3></div>
        <div v-if="distTotal" class="donut-wrap">
          <svg class="donut" viewBox="0 0 140 140">
            <circle cx="70" cy="70" r="54" fill="none" stroke="#eef2f0" stroke-width="22" />
            <circle
              v-for="arc in donutArcs"
              :key="arc.key"
              cx="70"
              cy="70"
              r="54"
              fill="none"
              :stroke="arc.color"
              stroke-width="22"
              :stroke-dasharray="arc.dash"
              :stroke-dashoffset="arc.offset"
              transform="rotate(-90 70 70)"
            />
            <text x="70" y="66" text-anchor="middle" font-size="19" font-weight="800" fill="#1f2421">
              {{ fmt(distTotal) }}
            </text>
            <text x="70" y="84" text-anchor="middle" font-size="9" fill="#8b9491">
              {{ lang.t('stat.total') }}
            </text>
          </svg>
          <div class="legend">
            <div v-for="seg in distSegs" :key="seg.key" class="legend-row">
              <span class="legend-dot" :style="{ background: seg.color }"></span>
              <span class="legend-name">{{ seg.name }}</span>
              <span class="legend-val">{{ fmt(seg.value) }}</span>
            </div>
          </div>
        </div>
        <p v-else class="board-empty">{{ lang.t('board.emptyChart') }}</p>
      </div>

      <!-- 图 3：最近 7 天检测趋势（柱状，横跨整行） -->
      <div class="panel panel--wide">
        <div class="panel-head"><AppIcon name="trend" /><h3>{{ lang.t('board.trend7') }}</h3></div>
        <div v-if="hasTrend" class="bar-chart">
          <div v-for="(point, i) in trend" :key="i" class="bar-col" :title="point.value">
            <div class="bar" :style="{ height: Math.max(3, (point.value / trendMax) * 100) + '%' }"></div>
            <div class="bar-label" :class="{ 'is-hidden': i % labelStep !== 0 }">{{ point.label }}</div>
          </div>
        </div>
        <p v-else class="board-empty">{{ lang.t('board.emptyDetect') }}</p>
      </div>
    </div>
  </section>
</template>
