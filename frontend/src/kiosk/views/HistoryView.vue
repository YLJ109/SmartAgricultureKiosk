<script setup>
/* 历史记录：检测 / 问答两个列表；每条可展开详情、可打印；页头可一键打印全部 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import { useToast } from '../components/useToast'
import { useLangStore } from '../stores/lang'
import { api, errText } from '../api'
import { SEVERITY_KEY } from '../i18n'

const router = useRouter()
const lang = useLangStore()
const toast = useToast()

const tab = ref('detect')
const items = ref([])
const total = ref(0)
const loading = ref(false)
const expanded = ref('') // 当前展开的 record_no
const detailCache = ref({}) // record_no -> RecordDetail

const printRecords = ref([])
const printTitle = ref('')

const PAGE_SIZE = 20

async function load() {
  loading.value = true
  expanded.value = ''
  try {
    if (tab.value === 'detect') {
      const page = await api.history({ page: 1, page_size: PAGE_SIZE, lang: lang.code })
      items.value = page.items || []
      total.value = page.total || 0
    } else {
      const page = await api.historyChats({ page: 1, page_size: PAGE_SIZE })
      items.value = page.items || []
      total.value = page.total || 0
    }
  } catch (err) {
    // 按 code 取当前语言文案（如 forbidden / not_found）；t() 依赖 this.code，
    // 故包一层箭头函数保住 this 绑定
    toast.error(errText(err, (k) => lang.t(k)))
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function fmtTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  try {
    return date.toLocaleString(lang.code, { hour12: false })
  } catch (e) {
    return date.toLocaleString()
  }
}

function severityText(severity) {
  return lang.t(SEVERITY_KEY[severity] || 'severity.info')
}

async function fetchDetail(recordNo) {
  if (detailCache.value[recordNo]) return detailCache.value[recordNo]
  const detail = await api.historyDetail(recordNo, lang.code)
  detailCache.value = { ...detailCache.value, [recordNo]: detail }
  return detail
}

async function toggleDetail(item) {
  // 只有检测记录能展开详情：详情接口 /api/history/{record_no} 查的是检测表。
  // 问答记录没有 record_no 字段，放行会拼出 /api/history/undefined 并 404。
  // 这里在函数层拦截 —— 整行（.record-open）与「详情」按钮都会调到它，只改按钮会漏掉整行。
  if (tab.value !== 'detect') return
  if (expanded.value === item.record_no) {
    expanded.value = ''
    return
  }
  try {
    await fetchDetail(item.record_no)
    expanded.value = item.record_no
  } catch (err) {
    toast.error(errText(err, (k) => lang.t(k)))
  }
}

function doPrint(records, title) {
  printRecords.value = records
  printTitle.value = title
  toast.info(lang.t('history.printed'))
  nextTick(() => window.print())
}

async function printOne(item) {
  try {
    if (tab.value === 'detect') {
      const detail = await fetchDetail(item.record_no)
      doPrint([{ kind: 'detect', ...detail }], lang.t('history.detectTag'))
    } else {
      doPrint([{ kind: 'chat', question: item.question, answer: item.answer, created_at: item.created_at }], lang.t('history.chatTag'))
    }
  } catch (err) {
    toast.error(errText(err, (k) => lang.t(k)))
  }
}

async function printAll() {
  if (!items.value.length) {
    toast.error(lang.t('history.empty'))
    return
  }
  if (tab.value === 'detect') {
    doPrint(items.value.map((item) => ({ kind: 'detect-brief', ...item })), lang.t('history.detectTag'))
  } else {
    doPrint(
      items.value.map((item) => ({ kind: 'chat', question: item.question, answer: item.answer, created_at: item.created_at })),
      lang.t('history.chatTag'),
    )
  }
}

const countText = computed(() => lang.t('history.count', { n: total.value }))

onMounted(load)

watch(tab, load)
watch(
  () => lang.code,
  () => {
    // 记录内容按语言快照存储，切语言要重新拉一次列表与已展开详情
    detailCache.value = {}
    load()
  },
)
</script>

<template>
  <!-- view--scroll：历史记录条目不封顶，这一页不做整屏固定，让内容自然排布、由主区域滚动 -->
  <section class="view view--scroll">
    <div class="page-head">
      <button class="ag-btn ag-btn-ghost" type="button" @click="router.push('/')">
        <AppIcon name="arrowRight" style="transform: rotate(180deg)" />
        <span>{{ lang.t('nav.back') }}</span>
      </button>
      <div class="page-head-main">
        <span class="page-title">{{ lang.t('history.title') }}</span>
        <span class="page-sub">{{ lang.t('history.sub') }}</span>
      </div>

      <div class="spacer"></div>

      <div class="seg">
        <button type="button" :class="{ on: tab === 'detect' }" @click="tab = 'detect'">
          {{ lang.t('history.detectTag') }}
        </button>
        <button type="button" :class="{ on: tab === 'chat' }" @click="tab = 'chat'">
          {{ lang.t('history.chatTag') }}
        </button>
      </div>

      <span class="tag tag-plain">{{ countText }}</span>

      <button class="ag-btn ag-btn-primary ag-btn-sm" type="button" @click="printAll">
        <AppIcon name="file" />
        <span>{{ lang.t('history.printAll') }}</span>
      </button>
    </div>

    <div class="record-list">
      <div v-if="!items.length" class="result-empty">
        <AppIcon name="history" />
        <div class="re-title">{{ lang.t('history.empty') }}</div>
      </div>

      <div v-for="item in items" :key="tab + '-' + item.id" class="record-item">
        <div class="record-row">
          <button class="record-open" type="button" @click="toggleDetail(item)">
            <template v-if="tab === 'detect'">
              <img v-if="item.image_url" class="record-thumb" :src="item.image_url" alt="" />
              <span v-else class="record-icon" :style="{ background: 'linear-gradient(135deg,#f7bb2d,#e59500)' }">
                <AppIcon name="bug" />
              </span>
              <span class="record-main">
                <span class="record-title">{{ item.crop }} · {{ item.name || lang.t('cat.unknown') }}</span>
                <span class="record-sub">{{ item.record_no }} · {{ severityText(item.severity) }}</span>
              </span>
            </template>
            <template v-else>
              <span class="record-icon" :style="{ background: 'linear-gradient(135deg,#3d8bf2,#1a73e8)' }">
                <AppIcon name="chat" />
              </span>
              <span class="record-main">
                <span class="record-title">{{ item.question }}</span>
                <span class="record-sub">{{ fmtTime(item.created_at) }}</span>
              </span>
            </template>
          </button>

          <div class="record-side">
            <span class="tag" :class="tab === 'detect' ? 'tag-success' : 'tag-info'">
              {{ tab === 'detect' ? lang.t('history.detectTag') : lang.t('history.chatTag') }}
            </span>
            <span class="record-time">
              {{ tab === 'detect' ? fmtTime(item.created_at) + ' · ' + item.confidence + '%' : '' }}
            </span>
            <div class="record-btns">
              <!-- 「详情」只对检测记录有意义：详情接口 /api/history/{record_no} 查的是检测表，
                   拿问答记录的编号去查必然 404。而问答的问答内容本来就显示在上方，无需再取详情。 -->
              <button v-if="tab === 'detect'" class="record-btn" type="button" @click="toggleDetail(item)">
                <AppIcon name="search" />
                <span>{{ expanded === item.record_no ? lang.t('common.close') : lang.t('history.detail') }}</span>
              </button>
              <button class="record-btn" type="button" @click="printOne(item)">
                <AppIcon name="file" />
                <span>{{ lang.t('history.print') }}</span>
              </button>
            </div>
          </div>
        </div>

        <div v-if="tab === 'detect' && expanded === item.record_no && detailCache[item.record_no]" class="record-detail">
          <!-- 这里原本显示拉丁学名（如 Aphidoidea）。它是外语且不可本地化，已移除 -->
          <div v-if="detailCache[item.record_no].crop" class="record-sub">
            {{ lang.t('detect.confidence') }}: {{ detailCache[item.record_no].confidence }}%
          </div>
          <div v-if="detailCache[item.record_no].symptoms && detailCache[item.record_no].symptoms.length">
            <strong>{{ lang.t('detect.symptoms') }}</strong>
            <ul class="info-block" style="border: none; margin: 0; padding: 0">
              <li v-for="(s, i) in detailCache[item.record_no].symptoms" :key="i">{{ s }}</li>
            </ul>
          </div>
          <div v-if="detailCache[item.record_no].cause">
            <strong>{{ lang.t('detect.cause') }}</strong>
            <div class="k-plain">{{ detailCache[item.record_no].cause }}</div>
          </div>
          <div v-if="detailCache[item.record_no].treatment && detailCache[item.record_no].treatment.length">
            <strong>{{ lang.t('detect.treatment') }}</strong>
            <ul class="info-block" style="border: none; margin: 0; padding: 0">
              <li v-for="(s, i) in detailCache[item.record_no].treatment" :key="i">{{ s }}</li>
            </ul>
          </div>
          <div v-if="detailCache[item.record_no].pesticide && detailCache[item.record_no].pesticide.length">
            <strong>{{ lang.t('detect.pesticide') }}</strong>
            <ul class="info-block" style="border: none; margin: 0; padding: 0">
              <li v-for="(s, i) in detailCache[item.record_no].pesticide" :key="i">{{ s }}</li>
            </ul>
          </div>
        </div>
      </div>
    </div>

    <!-- 打印单：屏幕上隐藏，@media print 时只显示这一块 -->
    <div class="print-sheet print-only">
      <h2 style="font-size: 1.3rem; margin-bottom: 12px">{{ printTitle }}</h2>
      <div v-for="(rec, i) in printRecords" :key="i" class="info-block" style="margin-top: 12px">
        <template v-if="rec.kind === 'chat'">
          <div class="k-plain"><strong>Q:</strong> {{ rec.question }}</div>
          <div class="k-plain"><strong>A:</strong> {{ rec.answer }}</div>
        </template>
        <template v-else>
          <div class="result-name" style="font-size: 1.2rem">
            {{ rec.crop }} · {{ rec.name || lang.t('cat.unknown') }}
          </div>
          <div class="record-sub">
            {{ lang.t('detect.recordNo') }}: {{ rec.record_no }} · {{ lang.t('detect.confidence') }}:
            {{ rec.confidence }}% · {{ severityText(rec.severity) }}
          </div>
          <ul v-if="rec.symptoms && rec.symptoms.length" style="margin-top: 6px">
            <li v-for="(s, j) in rec.symptoms" :key="'s' + j">{{ s }}</li>
          </ul>
          <div v-if="rec.cause" class="k-plain">{{ rec.cause }}</div>
          <ul v-if="rec.treatment && rec.treatment.length" style="margin-top: 6px">
            <li v-for="(s, j) in rec.treatment" :key="'t' + j">{{ s }}</li>
          </ul>
          <ul v-if="rec.pesticide && rec.pesticide.length" style="margin-top: 6px">
            <li v-for="(s, j) in rec.pesticide" :key="'p' + j">{{ s }}</li>
          </ul>
        </template>
      </div>
    </div>
  </section>
</template>
