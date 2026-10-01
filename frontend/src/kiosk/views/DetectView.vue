<script setup>
/* 检测页：左取景（扫码 / 本机选图） + 右报告；页头内嵌「重新检测 / 语音播报 / 打印诊断单」 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import QRCode from 'qrcode'
import AppIcon from '../components/AppIcon.vue'
import { useToast } from '../components/useToast'
import { useLangStore } from '../stores/lang'
import { api, errText } from '../api'
import { CATEGORY_KEY, SEVERITY_KEY } from '../i18n'

const router = useRouter()
const lang = useLangStore()
const toast = useToast()

const fileInput = ref(null)
const mode = ref('pick') // pick | analyzing | result
const result = ref(null)
const previewUrl = ref('')
const confWidth = ref(0)
// 本次上传走哪个通道：本机选择 = local；扫码入口进来的 = qrcode
let pendingChannel = 'local'

const severityClass = computed(() => {
  const map = { high: 'tag-danger', medium: 'tag-accent', low: 'tag-info', info: 'tag-success' }
  return map[result.value && result.value.severity] || 'tag-plain'
})

// 检测框：后端给的是相对坐标（0~1），这里只做百分比换算，与图片渲染尺寸无关
const boxes = computed(() => {
  const list = result.value && result.value.boxes
  return Array.isArray(list) ? list : []
})

const severityText = computed(() =>
  result.value ? lang.t(SEVERITY_KEY[result.value.severity] || 'severity.info') : '',
)

const categoryText = computed(() =>
  result.value ? lang.t(CATEGORY_KEY[result.value.category] || 'cat.unknown') : '',
)

// 未命中知识库或命中参考条目时，必须提示「以农技员意见为准」
const showReferenceNote = computed(() =>
  !!result.value && (!result.value.matched || result.value.is_reference),
)

/* ---------- 微信扫码上传（真实可用）----------
   由后端开一次性会话，二维码里放的**就是后端那张手机上传页的真实地址**：
   农户用微信扫一扫打开 -> 拍照 -> 照片直接 POST 回后端 -> 这里轮询取件 -> 走正常识别流程。
   二维码用 qrcode 库真实编码生成，任何扫码工具都能解析，不再是画着好看的占位图形。 */
const qrSvg = ref('')
const qrUrl = ref('')
let qrToken = ''
let qrTimer = null

async function openQrSession() {
  try {
    const session = await api.mobileSession()
    qrToken = session.token
    qrUrl.value = session.url
    // type=svg：直接拿到可内联的矢量图，任意分辨率都不糊，也不用额外的 canvas
    qrSvg.value = await QRCode.toString(session.url, {
      type: 'svg',
      margin: 1,
      errorCorrectionLevel: 'M',
    })
    // 后端探测不到局域网地址时会退回 127.0.0.1，那种地址手机是打不开的，得先提示
    if (!session.reachable) toast.info(lang.t('detect.qrOffline'))
    startPolling(session.poll_interval_ms || 2000)
  } catch (err) {
    qrSvg.value = ''
    toast.error(errText(err, (k) => lang.t(k)))
  }
}

function stopPolling() {
  if (qrTimer) {
    clearInterval(qrTimer)
    qrTimer = null
  }
}

/* 轮询取件：手机传上来的照片在这里被取回，再当作一次普通上传交给识别接口。
   只在取景态轮询 —— 出了结果还继续轮询，会把用户根本没在看的照片也吃掉。 */
function startPolling(interval) {
  stopPolling()
  qrTimer = setInterval(async () => {
    if (!qrToken || mode.value !== 'pick') return
    try {
      const pending = await api.mobilePending(qrToken)
      if (pending.expired) {
        // 二维码过期就直接换一张新的，而不是让农户对着失效的码反复扫
        stopPolling()
        openQrSession()
        return
      }
      if (!pending.ready) return
      stopPolling()
      const blob = await (await fetch(pending.image_url)).blob()
      submit(new File([blob], 'phone.jpg', { type: blob.type || 'image/jpeg' }), 'qrcode')
    } catch (e) {
      /* 网络抖一下不打断轮询，下一轮再试 */
    }
  }, interval)
}

/* 点卡片 = 重新生成二维码（手动续期，或换一张更新的） */
function onQr() {
  openQrSession()
}

function revokePreview() {
  if (previewUrl.value && previewUrl.value.startsWith('blob:')) URL.revokeObjectURL(previewUrl.value)
}

function pickFile() {
  if (fileInput.value) fileInput.value.click()
}

function onFile(event) {
  const input = event.target
  const file = input.files && input.files[0]
  input.value = ''
  if (!file) {
    pendingChannel = 'local'
    return
  }
  const channel = pendingChannel
  pendingChannel = 'local'
  submit(file, channel)
}

async function submit(file, channel) {
  revokePreview()
  previewUrl.value = URL.createObjectURL(file)
  mode.value = 'analyzing'
  result.value = null
  confWidth.value = 0

  try {
    const res = await api.recognize(file, { lang: lang.code, crop: '', channel })
    result.value = res
    if (res.image_url) previewUrl.value = res.image_url
    mode.value = 'result'
    setTimeout(() => {
      confWidth.value = res.confidence || 0
    }, 60)
  } catch (err) {
    // 按 code 取当前语言文案；t() 依赖 this.code，包一层箭头函数保住 this 绑定
    toast.error(errText(err, (k) => lang.t(k)))
    mode.value = 'pick'
    revokePreview()
    previewUrl.value = ''
  }
}

function resetAll() {
  if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel()
  revokePreview()
  previewUrl.value = ''
  result.value = null
  confWidth.value = 0
  mode.value = 'pick'
}

const VOICE_PREFIX = {
  'zh-CN': 'zh',
  'en-US': 'en',
  'ug-CN': 'ug',
  'kk-CN': 'kk',
  'bo-CN': 'bo',
  'mn-CN': 'mn',
}

function speakResult() {
  if (!result.value) return
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
    toast.error(lang.t('detect.speakUnsupported'))
    return
  }
  const r = result.value
  const text = [r.name, ...(r.symptoms || []), ...(r.treatment || [])].filter(Boolean).join('。')
  if (!text) return

  const synth = window.speechSynthesis
  synth.cancel()
  const utter = new SpeechSynthesisUtterance(text)
  const voices = synth.getVoices ? synth.getVoices() : []
  const wanted = (VOICE_PREFIX[lang.code] || 'zh').toLowerCase()
  // 有对应语音包就用，没有就退回中文播报
  const voice =
    voices.find((v) => String(v.lang).toLowerCase().startsWith(wanted)) ||
    voices.find((v) => String(v.lang).toLowerCase().startsWith('zh'))
  utter.lang = voice ? voice.lang : lang.code
  if (voice) utter.voice = voice
  synth.speak(utter)
  toast.info(lang.t('detect.speaking'))
}

function printReport() {
  toast.info(lang.t('detect.printed'))
  window.print()
}

// 切换语言后，已出的报告按新语言重新取一次详情，保证文案立即跟着变
watch(
  () => lang.code,
  async () => {
    if (!result.value || !result.value.record_no) return
    try {
      const detail = await api.historyDetail(result.value.record_no, lang.code)
      result.value = { ...result.value, ...detail }
    } catch (e) {
      /* 拉不到就保留原语言结果，不打扰用户 */
    }
  },
)

onMounted(openQrSession)

onBeforeUnmount(() => {
  stopPolling()
  if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel()
  revokePreview()
})
</script>

<template>
  <section class="view">
    <!-- 页头是唯一主盒子：返回 + 标题（单行） + 结果出来后才出现的三个动作 -->
    <div class="page-head">
      <button class="ag-btn ag-btn-ghost" type="button" @click="router.push('/')">
        <AppIcon name="arrowRight" style="transform: rotate(180deg)" />
        <span>{{ lang.t('nav.back') }}</span>
      </button>
      <div class="page-head-main">
        <span class="page-title">{{ lang.t('detect.title') }}</span>
        <span class="page-sub">{{ lang.t('detect.sub') }}</span>
      </div>

      <div class="spacer"></div>

      <div v-if="mode === 'result'" class="result-actions">
        <button class="ag-btn ag-btn-ghost" type="button" @click="resetAll">
          <AppIcon name="history" />
          <span>{{ lang.t('detect.again') }}</span>
        </button>
        <button class="ag-btn ag-btn-ghost" type="button" @click="speakResult">
          <AppIcon name="chat" />
          <span>{{ lang.t('detect.speak') }}</span>
        </button>
        <button class="ag-btn ag-btn-primary" type="button" @click="printReport">
          <AppIcon name="file" />
          <span>{{ lang.t('detect.print') }}</span>
        </button>
      </div>
    </div>

    <div class="detect-split">
      <!-- 左：第一步 · 取景 / 选图 -->
      <div class="panel photo-panel">
        <div class="panel-head">
          <AppIcon name="camera" />
          <h3>{{ lang.t('detect.photoTitle') }}</h3>
        </div>

        <div v-if="mode === 'pick'" class="pick-zone">
          <button class="qr-card" type="button" @click="onQr">
            <span class="qr-img" v-html="qrSvg"></span>
            <span class="qr-text">
              <span class="qr-title">{{ lang.t('detect.qrTitle') }}</span>
              <span class="qr-hint">{{ lang.t('detect.qrHint') }}</span>
            </span>
          </button>

          <div class="or-line"><span>{{ lang.t('common.or') }}</span></div>

          <div
            class="upload-box"
            role="button"
            tabindex="0"
            @click="pickFile"
            @keydown.enter.prevent="pickFile"
            @keydown.space.prevent="pickFile"
          >
            <AppIcon name="camera" />
            <div class="t1">{{ lang.t('detect.local') }}</div>
            <div class="t2">{{ lang.t('detect.uploadHint') }}</div>
          </div>
        </div>

        <template v-else>
          <div class="preview-wrap">
            <!-- preview-frame 收缩包裹图片，检测框图层 inset:0 就能精准对齐图片本身，
                 而不是整个取景区（否则图片居中留白时框会错位） -->
            <div class="preview-frame">
              <img class="preview-img" :src="previewUrl" alt="crop photo" />

              <!-- 检测框用 DOM 而不是 canvas 画：文字交给浏览器按 CSS 字体渲染，
                   中文/维文/藏文/蒙文都不会出现 canvas 上的方块字（乱码） -->
              <div v-if="boxes.length" class="box-layer">
                <div
                  v-for="(b, i) in boxes"
                  :key="i"
                  class="det-box"
                  :style="{
                    left: b.x * 100 + '%',
                    top: b.y * 100 + '%',
                    width: b.w * 100 + '%',
                    height: b.h * 100 + '%',
                  }"
                >
                  <span class="det-label" :class="{ 'is-inside': b.y < 0.09 }">
                    {{ result.name }} {{ Math.round(b.score * 100) }}%
                  </span>
                </div>
              </div>
            </div>

            <div v-if="mode === 'analyzing'" class="analyzing-overlay">
              <div class="typing"><span></span><span></span><span></span></div>
              <div class="an-title">{{ lang.t('detect.analyzing') }}</div>
              <div class="an-hint">{{ lang.t('detect.analyzingHint') }}</div>
            </div>
          </div>

          <div v-if="mode === 'result' && boxes.length" class="box-note">
            {{ lang.t('detect.boxNote') }}
          </div>
        </template>

        <input ref="fileInput" class="hidden" type="file" accept="image/*" @change="onFile" />
      </div>

      <!-- 右：第二步 · 识别报告（打印时只打印这里） -->
      <div class="panel report-panel">
        <div class="panel-head">
          <AppIcon name="shield" />
          <h3>{{ lang.t('detect.resultTitle') }}</h3>
        </div>

        <div class="report-scroll print-sheet">
          <div v-if="!result" class="result-empty">
            <AppIcon name="scan" />
            <div class="re-title">{{ lang.t('detect.emptyTitle') }}</div>
            <div class="re-hint">{{ lang.t('detect.emptyHint') }}</div>
          </div>

          <div v-else>
            <!-- 打印单上的照片：屏幕上不显示（.print-only），只在打印时出现。
                 必须放在 .print-sheet 内部 —— 打印样式用 visibility 过滤，
                 这个容器之外的内容一律不可见。检测框一起带上，纸质单据才能对照。 -->
            <figure v-if="previewUrl" class="print-photo print-only">
              <div class="print-photo-frame">
                <img :src="previewUrl" alt="crop photo" />
                <div v-if="boxes.length" class="box-layer">
                  <div
                    v-for="(b, i) in boxes"
                    :key="i"
                    class="det-box"
                    :style="{
                      left: b.x * 100 + '%',
                      top: b.y * 100 + '%',
                      width: b.w * 100 + '%',
                      height: b.h * 100 + '%',
                    }"
                  >
                    <span class="det-label" :class="{ 'is-inside': b.y < 0.09 }">
                      {{ result.name }} {{ Math.round(b.score * 100) }}%
                    </span>
                  </div>
                </div>
              </div>
              <figcaption v-if="boxes.length">{{ lang.t('detect.boxNote') }}</figcaption>
            </figure>

            <div class="result-meta">
              <span class="tag" :class="severityClass">
                <AppIcon name="alert" />
                <span>{{ severityText }}</span>
              </span>
              <span class="tag tag-plain">
                {{ lang.t('detect.recordNo') }}: {{ result.record_no }}
              </span>
              <span class="tag tag-plain">{{ categoryText }}</span>
              <span v-if="result.crop" class="tag tag-plain">{{ result.crop }}</span>
            </div>

            <div v-if="showReferenceNote" class="report-note">
              <AppIcon name="alert" />
              <span>{{ lang.t('detect.reference') }}</span>
            </div>

            <!-- 不显示拉丁学名：它是外语（如 Aphidoidea），没法按当前语言本地化，
                 对老年农户也没有实用价值；本地语言的名字上一行已经给了 -->
            <div class="result-name">{{ result.name || lang.t('cat.unknown') }}</div>

            <div class="confidence">
              <div class="confidence-top">
                <span>{{ lang.t('detect.confidence') }}</span>
                <span>{{ result.confidence }}%</span>
              </div>
              <div class="confidence-bar">
                <div class="confidence-fill" :style="{ width: confWidth + '%' }"></div>
              </div>
            </div>

            <div v-if="result.symptoms && result.symptoms.length" class="info-block">
              <div class="k"><AppIcon name="alert" /><span>{{ lang.t('detect.symptoms') }}</span></div>
              <ul>
                <li v-for="(item, i) in result.symptoms" :key="i">{{ item }}</li>
              </ul>
            </div>

            <div v-if="result.cause" class="info-block">
              <div class="k"><AppIcon name="drop" /><span>{{ lang.t('detect.cause') }}</span></div>
              <div class="k-plain">{{ result.cause }}</div>
            </div>

            <div v-if="result.treatment && result.treatment.length" class="info-block">
              <div class="k"><AppIcon name="shield" /><span>{{ lang.t('detect.treatment') }}</span></div>
              <ul>
                <li v-for="(item, i) in result.treatment" :key="i">{{ item }}</li>
              </ul>
            </div>

            <div v-if="result.pesticide && result.pesticide.length" class="info-block">
              <div class="k"><AppIcon name="bug" /><span>{{ lang.t('detect.pesticide') }}</span></div>
              <ul>
                <li v-for="(item, i) in result.pesticide" :key="i">{{ item }}</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
