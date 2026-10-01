<script setup>
/* 农事顾问：对话流 + 4 个快捷提问 + 输入行 */
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import { useToast } from '../components/useToast'
import { useLangStore } from '../stores/lang'
import { api, errText } from '../api'

const router = useRouter()
const lang = useLangStore()
const toast = useToast()

const logEl = ref(null)
const input = ref('')
const thinking = ref(false)
const quicks = ref([])
let seq = 0

// 欢迎语用 i18nKey 存，切换语言时能跟着变；服务端返回的问答按当时语言固定
const messages = ref([{ id: ++seq, who: 'ai', i18nKey: 'chat.hello' }])

function textOf(msg) {
  return msg.i18nKey ? lang.t(msg.i18nKey) : msg.text
}

async function scrollToEnd() {
  await nextTick()
  if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
}

async function loadQuicks() {
  try {
    const list = await api.chatQuicks(lang.code)
    if (Array.isArray(list) && list.length) {
      quicks.value = list
      return
    }
  } catch (e) {
    /* 后端不可用时退回内置词条，保证按钮不空 */
  }
  quicks.value = ['chat.q1', 'chat.q2', 'chat.q3', 'chat.q4'].map((key) => ({ key, text: lang.t(key) }))
}

async function ask(question) {
  const text = (question || '').trim()
  if (!text || thinking.value) return

  messages.value.push({ id: ++seq, who: 'user', text })
  // 先把 AI 气泡摆上去（空的），字一到就往上长。
  // 比"转圈 9 秒再整段蹦出来"体感好得多 —— 老人看到字在动就知道机器在干活。
  messages.value.push({ id: ++seq, who: 'ai', text: '', streaming: true })
  // 注意：必须从数组里取回代理对象再改。直接改 push 进去的那个原始对象不会触发视图更新。
  const bubble = messages.value[messages.value.length - 1]
  thinking.value = true
  await scrollToEnd()

  let meta = null
  try {
    await api.chatStream(text, lang.code, {
      onDelta: (piece) => {
        thinking.value = false // 收到第一块就撤掉"正在输入"动画
        bubble.text += piece
        scrollToEnd()
      },
      onMeta: (m) => {
        meta = m
      },
    })
    // 大模型调用失败降级为本地知识库时，轻描淡写提示一下
    if (meta && meta.source === 'fallback') bubble.fallbackNote = 'chat.fallbackNote'
  } catch (err) {
    // 按 code 取当前语言文案；t() 依赖 this.code，包一层箭头函数保住 this 绑定
    toast.error(errText(err, (k) => lang.t(k)))
    // 一个字都没吐出来就把空气泡撤掉，别留个白框让人以为卡住了
    if (!bubble.text) messages.value = messages.value.filter((m) => m.id !== bubble.id)
  } finally {
    bubble.streaming = false
    thinking.value = false
    scrollToEnd()
  }
}

function send() {
  const text = input.value.trim()
  if (!text) return
  input.value = ''
  ask(text)
}

onMounted(() => {
  loadQuicks()
  scrollToEnd()
})

watch(
  () => lang.code,
  () => {
    loadQuicks()
  },
)
</script>

<template>
  <section class="view">
    <div class="page-head">
      <button class="ag-btn ag-btn-ghost" type="button" @click="router.push('/')">
        <AppIcon name="arrowRight" style="transform: rotate(180deg)" />
        <span>{{ lang.t('nav.back') }}</span>
      </button>
      <div class="page-head-main">
        <span class="page-title">{{ lang.t('chat.title') }}</span>
        <span class="page-sub">{{ lang.t('chat.sub') }}</span>
      </div>
    </div>

    <div class="panel chat-wrap">
      <div ref="logEl" class="chat-log">
        <div v-for="msg in messages" :key="msg.id" class="msg" :class="msg.who">
          <div class="msg-avatar">
            <AppIcon :name="msg.who === 'ai' ? 'leaf' : 'user'" />
          </div>
          <div class="bubble">
            <!-- 首字还没到：气泡里转三个点；字一到就换成正文 + 光标 -->
            <div v-if="msg.streaming && !msg.text" class="typing">
              <span></span><span></span><span></span>
            </div>
            <template v-else>{{ textOf(msg) }}<span v-if="msg.streaming" class="caret"></span></template>
            <span v-if="msg.fallbackNote" class="bubble-note">{{ lang.t(msg.fallbackNote) }}</span>
          </div>
        </div>
      </div>

      <div class="quick-asks">
        <button
          v-for="item in quicks"
          :key="item.key"
          class="quick-ask"
          type="button"
          @click="ask(item.text)"
        >
          {{ item.text }}
        </button>
      </div>

      <div class="chat-input-row">
        <input
          v-model="input"
          type="text"
          :placeholder="lang.t('chat.ph')"
          @keydown.enter.prevent="send"
        />
        <button class="ag-btn ag-btn-primary" type="button" :disabled="thinking" @click="send">
          <AppIcon name="send" />
          <span>{{ lang.t('chat.send') }}</span>
        </button>
      </div>
    </div>
  </section>
</template>
