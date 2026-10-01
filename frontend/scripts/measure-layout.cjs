/**
 * 终端端布局实测工具（靠 Chrome DevTools Protocol 量真实几何，不靠读 CSS 猜）
 *
 * 为什么需要它：整屏固定布局的高度链一旦断掉，表现是"内容超出页面且滚不动"，
 * 而这种问题光看 CSS 很难判断到底是哪一层的约束没生效。这个脚本直接量出来。
 *
 * 用法：
 *   1. 先启动后端(8002) 与前端 dev server(5189)
 *   2. node scripts/measure-layout.cjs
 *
 * 它会：启动无头 Chrome(1920×1080) → 打开终端端 → 点「游客模式」进首页
 *      → 进「拍照识病」→ 用 canvas 现场造一张"病叶图"塞进 file input 真实走一遍上传
 *      → 分别量取景态与结果态的关键元素高度、是否页面滚动、内部是否可滚。
 */

const { spawn } = require('node:child_process')
const os = require('node:os')
const path = require('node:path')
const fs = require('node:fs')

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean)

const PORT = Number(process.env.CDP_PORT || 9333)
const TARGET_URL = process.env.KIOSK_URL || 'http://localhost:5189/'
// 窗口尺寸可覆盖：小窗口才能暴露"内容超出视口却滚不动"的问题
const SIZE = process.env.KIOSK_SIZE || '1920,1080'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

function findBrowser() {
  for (const p of CHROME_CANDIDATES) {
    if (fs.existsSync(p)) return p
  }
  throw new Error('未找到 Chrome / Edge，可用环境变量 CHROME_PATH 指定')
}

async function waitForTarget() {
  for (let i = 0; i < 40; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
      const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl)
      if (page) return page
    } catch {
      /* 端口还没起来，继续等 */
    }
    await sleep(300)
  }
  throw new Error('Chrome 调试端口未就绪')
}

/** 极简 CDP 客户端：Node 22+ 自带全局 WebSocket，不需要任何依赖 */
function connect(url) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url)
    let id = 0
    const pending = new Map()

    ws.addEventListener('open', () =>
      resolve({
        send(method, params = {}) {
          const msgId = ++id
          ws.send(JSON.stringify({ id: msgId, method, params }))
          return new Promise((res, rej) => pending.set(msgId, { res, rej }))
        },
        close: () => ws.close(),
      }),
    )
    ws.addEventListener('error', reject)
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data)
      if (!msg.id || !pending.has(msg.id)) return
      const { res, rej } = pending.get(msg.id)
      pending.delete(msg.id)
      if (msg.error) rej(new Error(JSON.stringify(msg.error)))
      else res(msg.result)
    })
  })
}

async function evaluate(cdp, expression) {
  const out = await cdp.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  if (out.exceptionDetails) {
    throw new Error('页面内异常：' + (out.exceptionDetails.exception?.description || JSON.stringify(out.exceptionDetails)))
  }
  return out.result.value
}

/** 一次性把关心的几何量全量回来 */
const MEASURE = `(() => {
  const q = (s) => document.querySelector(s)
  const rect = (s) => {
    const el = q(s)
    if (!el) return null
    const r = el.getBoundingClientRect()
    return { w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top), bottom: Math.round(r.bottom) }
  }
  const sc = document.scrollingElement
  const rep = q('.report-scroll')
  const pick = q('.pick-zone')
  const upload = q('.upload-box')
  const vh = window.innerHeight
  return {
    viewport: window.innerWidth + 'x' + vh,
    rootFont: getComputedStyle(document.documentElement).fontSize,
    页面滚动: sc ? sc.scrollHeight > sc.clientHeight + 1 : null,
    页面_scrollH_clientH: sc ? sc.scrollHeight + '/' + sc.clientHeight : null,
    pageHead: rect('.page-head'),
    detectSplit: rect('.detect-split'),
    photoPanel: rect('.photo-panel'),
    reportPanel: rect('.report-panel'),
    pickZone: rect('.pick-zone'),
    qrCard: rect('.qr-card'),
    uploadBox: rect('.upload-box'),
    upload是否超出视口: upload ? upload.getBoundingClientRect().bottom > vh + 1 : null,
    previewWrap: rect('.preview-wrap'),
    previewImg: rect('.preview-img'),
    reportScroll: rect('.report-scroll'),
    报告内部可滚: rep ? rep.scrollHeight > rep.clientHeight + 1 : null,
    报告_scrollH_clientH: rep ? rep.scrollHeight + '/' + rep.clientHeight : null,
    pickZone内容溢出: pick ? pick.scrollHeight > pick.clientHeight + 1 : null,
  }
})()`

async function main() {
  const browser = findBrowser()
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'kiosk-cdp-'))
  const chrome = spawn(browser, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    '--window-size=' + SIZE,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-gpu',
    'about:blank',
  ])
  chrome.on('error', (e) => {
    console.error('启动浏览器失败：', e.message)
    process.exit(1)
  })

  let cdp
  let failed = false
  try {
    const target = await waitForTarget()
    cdp = await connect(target.webSocketDebuggerUrl)
    await cdp.send('Page.enable')
    await cdp.send('Runtime.enable')
    await cdp.send('Page.navigate', { url: TARGET_URL })
    await sleep(3500)

    // 登录页：语言选择必须在「进入系统 + 说明」两行之下
    const LOGIN_AUDIT = `(() => {
      const card = document.querySelector('.login-card')
      if (!card) return { 有登录卡: false }
      const sel = card.querySelector('.lang-select-wrap')
      const h2 = card.querySelector('h2')
      const hint = card.querySelector('.hint')
      if (!sel || !h2 || !hint) return { 有登录卡: true, 缺元素: { 语言: !!sel, 标题: !!h2, 说明: !!hint } }
      const r = (el) => el.getBoundingClientRect()
      return {
        有登录卡: true,
        语言选择在标题下方: r(sel).top >= r(h2).bottom - 1,
        语言选择在说明下方: r(sel).top >= r(hint).bottom - 1,
        卡片内顺序: [...card.children].map((c) => c.tagName.toLowerCase() + (c.className ? '.' + String(c.className).split(' ')[0] : '')),
        // 登录卡是毛玻璃（backdrop-filter blur）。这类属性被别的规则覆盖掉时页面不报错，
        // 只是悄悄退回普通白卡 —— 光看代码看不出来，所以在这里守一道。
        毛玻璃已生效: /blur/.test(getComputedStyle(card).backdropFilter || ''),
        卡片内容未溢出: card.scrollHeight <= card.clientHeight + 1,
      }
    })()`
    const loginLayout = await evaluate(cdp, LOGIN_AUDIT)
    console.log('\n=== 登录页布局 ===')
    console.log(JSON.stringify(loginLayout, null, 2))

    // 错误提示必须跟着语言走：切到维语后填一个非法手机号，看报错里还有没有汉字
    const errorI18n = await evaluate(
      cdp,
      `(async () => {
        const card = document.querySelector('.login-card')
        const sel = card && card.querySelector('.lang-select')
        if (!sel) return { 有下拉: false }
        sel.value = 'ug-CN'
        sel.dispatchEvent(new Event('change', { bubbles: true }))
        await new Promise((r) => setTimeout(r, 500))
        const nameEl = card.querySelector('input[autocomplete="name"]')
        const phoneEl = card.querySelector('input[type="tel"]')
        const setVal = (el, v) => { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })) }
        setVal(nameEl, 'تەكشۈرۈش')
        setVal(phoneEl, '123')            // 非法手机号，触发 bad_phone
        card.querySelector('.ag-btn-primary').click()
        await new Promise((r) => setTimeout(r, 1200))
        const err = card.querySelector('.login-error')
        const text = err ? err.textContent.trim() : ''
        // 还原成中文，避免影响后面的流程
        sel.value = 'zh-CN'
        sel.dispatchEvent(new Event('change', { bubbles: true }))
        await new Promise((r) => setTimeout(r, 400))
        return { 有下拉: true, 报错文案: text, 报错含汉字: /[\\u4e00-\\u9fff]/.test(text), 时长: text.length }
      })()`,
    )
    console.log('\n=== 报错文案本地化 ===')
    console.log(JSON.stringify(errorI18n, null, 2))

    /** 往登录卡里填内容并提交。tab: 'register' | 'login' */
    const fillCard = (tab, name, phone) => `(() => {
      const card = document.querySelector('.login-card')
      if (!card) return 'FAIL: 没有登录卡'
      const tabs = [...card.querySelectorAll('.login-tabs button')]
      const target = tabs[${tab === 'register' ? 1 : 0}]
      if (!target) return 'FAIL: 没有登录/注册页签'
      target.click()
      const setVal = (el, v) => {
        el.value = v
        // 直接改 value 不会触发 Vue 的 v-model，必须补发 input 事件
        el.dispatchEvent(new Event('input', { bubbles: true }))
      }
      const nameEl = card.querySelector('input[autocomplete="name"]')
      const phoneEl = card.querySelector('input[type="tel"]')
      if (!nameEl || !phoneEl) return 'FAIL: 缺姓名或手机号输入框'
      setVal(nameEl, ${JSON.stringify(name)})
      setVal(phoneEl, ${JSON.stringify(phone)})
      const submit = card.querySelector('.ag-btn-primary')
      if (!submit) return 'FAIL: 没有提交按钮'
      submit.click()
      return 'ok'
    })()`

    /** 一体机用户：先试注册（全新库），若提示已注册则改用登录页签。
        手机号现在是账号主键，只填姓名会被必填校验拦下，两个字段都要填。 */
    const kioskEnter = async (name, phone) => {
      const reg = await evaluate(cdp, fillCard('register', name, phone))
      await sleep(2200)
      if ((await evaluate(cdp, `location.pathname`)) === '/') return 'registered (' + reg + ')'
      const log = await evaluate(cdp, fillCard('login', name, phone))
      await sleep(2200)
      if ((await evaluate(cdp, `location.pathname`)) === '/') return 'logged-in (' + log + ')'
      const msg = await evaluate(
        cdp,
        `(() => { const e = document.querySelector('.login-error'); return e ? e.textContent.trim() : '(无错误提示)' })()`,
      )
      return 'FAIL: ' + msg
    }

    /** 游客进入（无姓名无手机号，走 /auth/guest） */
    const guestEnter = async () => {
      const r = await evaluate(
        cdp,
        `(() => {
          const b = [...document.querySelectorAll('button')].find(x => /游客|guest/i.test(x.textContent || ''))
          if (!b) return 'FAIL: 找不到游客按钮'
          b.click()
          return 'guest'
        })()`,
      )
      await sleep(2500)
      return r
    }

    const logout = async () => {
      const r = await evaluate(
        cdp,
        `(() => {
          const b = [...document.querySelectorAll('.term-topbar button')].find(x => /退出|logout|sign out/i.test(x.textContent || ''))
          if (!b) return 'FAIL: 找不到退出按钮'
          b.click()
          return 'OK'
        })()`,
      )
      await sleep(1800)
      return r
    }

    // 主流程用**正式账号**：游客已被锁定进不了历史与看板，
    // 拿游客去量这两页会量到首页，等于白测。
    console.log('登录（一体机账号）：', await kioskEnter('测量员', '13900000001'))

    // 首页也要量：这一页是"四卡铺满整屏"，高度链出问题时同样会被裁掉
    console.log('\n=== 首页 ===')
    const home = await evaluate(
      cdp,
      `(() => {
        const q = (s) => document.querySelector(s)
        const sc = document.scrollingElement
        const cards = [...document.querySelectorAll('.feature-card')]
        const grid = q('.feature-grid')
        const t0 = document.querySelector('.feature-text')
        return {
          viewport: window.innerWidth + 'x' + window.innerHeight,
          页面滚动: sc.scrollHeight > sc.clientHeight + 1,
          卡片数: cards.length,
          卡片高: cards.map(c => Math.round(c.getBoundingClientRect().height)),
          最低卡片底部: cards.length ? Math.round(Math.max(...cards.map(c => c.getBoundingClientRect().bottom))) : null,
          网格高: grid ? Math.round(grid.getBoundingClientRect().height) : null,
          // 文字块的 max-width 是否真的起作用：上限 vs 实际可用宽度
          文字块上限: t0 ? getComputedStyle(t0).maxWidth : null,
          文字块宽度: t0 ? Math.round(t0.getBoundingClientRect().width) : null,
          卡片可用内宽: cards.length ? Math.round(cards[0].getBoundingClientRect().width - 40) : null,
          上限是否生效: (() => {
            if (!t0 || !cards.length) return null
            const cap = parseFloat(getComputedStyle(t0).maxWidth)
            const avail = cards[0].getBoundingClientRect().width - 40
            return cap <= avail
          })(),
        }
      })()`,
    )
    console.log(JSON.stringify(home, null, 2))

    // 四张卡的插画挂在 ::after 上（background-image: 白色蒙层 + var(--fc-art)）。
    // 只读到 url 不算数：文件 404 或 SVG 本身损坏，表现和"有 url 没画面"一模一样，
    // 卡片会静悄悄退回原来的渐变底，光看代码看不出来。所以真的 new Image() 解码一遍。
    const art = await evaluate(
      cdp,
      `(async () => {
        const cards = [...document.querySelectorAll('.feature-card')]
        const urls = cards.map((c) => {
          const m = getComputedStyle(c, '::after').backgroundImage.match(/url\\("?([^")]+)"?\\)/)
          return m ? m[1] : null
        })
        const loaded = await Promise.all(urls.map((u) => new Promise((res) => {
          if (!u) return res(false)
          const img = new Image()
          img.onload = () => res(img.naturalWidth > 0)
          img.onerror = () => res(false)
          img.src = u
        })))
        return { 插画地址: urls, 插画是否加载成功: loaded }
      })()`,
    )
    console.log('\n=== 首页功能卡插画 ===')
    console.log(JSON.stringify(art, null, 2))

    const nav = await evaluate(
      cdp,
      `(() => {
        const cards = [...document.querySelectorAll('.feature-card')]
        const t = cards.find(c => /拍照|识病|diagnos/i.test(c.textContent||'')) || cards[0]
        if (!t) return 'FAIL: 没有功能卡'
        t.click()
        return 'OK -> ' + (t.textContent||'').trim().slice(0,16)
      })()`,
    )
    console.log('进入检测页：', nav)
    await sleep(1500)

    console.log('\n=== 取景态（未上传）===')
    const pick = await evaluate(cdp, MEASURE)
    console.log(JSON.stringify(pick, null, 2))

    // 二维码必须真的能扫。只断言"页面上有个 svg"证明不了任何事——之前的占位图形也有 svg。
    // 所以这里把它截成 PNG，交给 scripts/decode-qr.py 用 OpenCV 真解一次码。
    const qrBox = await evaluate(
      cdp,
      `(() => {
        const el = document.querySelector('.qr-img svg')
        if (!el) return null
        const r = el.getBoundingClientRect()
        return { x: r.x, y: r.y, w: r.width, h: r.height, viewBox: el.getAttribute('viewBox') }
      })()`,
    )
    console.log('\n=== 二维码 ===')
    console.log(JSON.stringify(qrBox, null, 2))
    if (qrBox && qrBox.w > 4) {
      const fs = require('fs')
      const path2 = require('path')
      const shot = await cdp.send('Page.captureScreenshot', {
        format: 'png',
        clip: { x: qrBox.x, y: qrBox.y, width: qrBox.w, height: qrBox.h, scale: 4 },
      })
      const out = path2.join(__dirname, 'qr-shot.png')
      fs.writeFileSync(out, Buffer.from(shot.data, 'base64'))
      console.log('已截图：' + out)
    }

    // 用后端 /static/samples/ 下那张真实病叶图上传，而不是 canvas 画的色块：
    // 合成色块本地 YOLO 检不出，会一路降级到"图片理解"，而那一级按设计**不产出检测框**
    // （它没有定位能力），于是"检测框渲染"这件事就永远验证不到、只能验证到空状态。
    // 换成真实病叶图，本地模型会真检出，框渲染才有得测；顺带也验证了 /static 代理是否配好。
    const up = await evaluate(
      cdp,
      `(async () => {
        const input = document.querySelector('input[type=file]')
        if (!input) return 'FAIL: 没有 file input'
        const resp = await fetch('/static/samples/corn-leaf-spots.jpg')
        if (!resp.ok) return 'FAIL: 示例图取不到，HTTP ' + resp.status
        const blob = await resp.blob()
        const dt = new DataTransfer()
        dt.items.add(new File([blob], 'leaf.jpg', { type: 'image/jpeg' }))
        input.files = dt.files
        input.dispatchEvent(new Event('change', { bubbles: true }))
        return 'OK'
      })()`,
    )
    console.log('\n上传：', up)

    // 识别现在可能要走联网的图片理解（2~4 秒），冷启动时还要等模型加载，
    // 所以上限给到 30 秒。原来按 15 秒写死，会在真实链路变慢时假失败。
    let ready = false
    for (let i = 0; i < 60; i++) {
      await sleep(500)
      const s = await evaluate(
        cdp,
        `(() => {
          const el = document.querySelector('.report-scroll')
          const t = el ? el.innerText : ''
          return /症状|防治|用药|置信/.test(t) ? 'yes' : 'no'
        })()`,
      )
      if (s === 'yes') {
        ready = true
        break
      }
    }
    console.log('识别结果渲染完成：', ready)

    console.log('\n=== 结果态（已上传）===')
    const after = await evaluate(cdp, MEASURE)
    console.log(JSON.stringify(after, null, 2))

    // 检测框审计：对齐 / 中文标签 / 置信度 / 不越界
    // 必须限定在屏幕预览的 .preview-frame 内：打印单里还有一份 .box-layer，
    // 它在屏幕上 display:none、尺寸为 0，不限定作用域会把两套框混在一起判。
    const BOX_AUDIT = `(() => {
      const scope = document.querySelector('.preview-frame')
      const img = scope ? scope.querySelector('.preview-img') : null
      const layer = scope ? scope.querySelector('.box-layer') : null
      const boxes = scope ? [...scope.querySelectorAll('.det-box')] : []
      const labels = scope ? [...scope.querySelectorAll('.det-label')] : []
      if (!img || !layer) return { 有图层: false, 框数: boxes.length }
      const r = (el) => { const b = el.getBoundingClientRect(); return { l: Math.round(b.left), t: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height) } }
      const ir = img.getBoundingClientRect(), lr = layer.getBoundingClientRect()
      const text = labels.map((l) => l.textContent.trim())
      const first = labels[0]
      return {
        有图层: true,
        框数: boxes.length,
        图片: r(img),
        图层: r(layer),
        图层与图片对齐: Math.abs(ir.left - lr.left) < 1.5 && Math.abs(ir.top - lr.top) < 1.5 &&
                       Math.abs(ir.width - lr.width) < 1.5 && Math.abs(ir.height - lr.height) < 1.5,
        框都在图片范围内: boxes.every((b) => {
          const x = b.getBoundingClientRect()
          return x.left >= lr.left - 4 && x.right <= lr.right + 4 && x.top >= lr.top - 4 && x.bottom <= lr.bottom + 4
        }),
        标签文本: text,
        标签含中文: text.some((v) => /[\\u4e00-\\u9fff]/.test(v)),
        标签含置信度: text.some((v) => /\\d+%/.test(v)),
        标签字体: first ? getComputedStyle(first).fontFamily : null,
        标签可见: labels.every((l) => {
          const x = l.getBoundingClientRect()
          return x.width > 8 && x.height > 8 && x.top >= lr.top - 30
        }),
      }
    })()`
    const boxAudit = await evaluate(cdp, BOX_AUDIT)
    console.log('\n=== 检测框审计 ===')
    console.log(JSON.stringify(boxAudit, null, 2))

    // 打印单：切到 print 媒体查一遍 —— 打印布局最容易"看着没事、打出来是空的"
    await cdp.send('Emulation.setEmulatedMedia', { media: 'print' })
    await sleep(400)
    const printAudit = await evaluate(
      cdp,
      `(() => {
        const fig = document.querySelector('.print-photo')
        const img = fig ? fig.querySelector('img') : null
        const labels = fig ? [...fig.querySelectorAll('.det-label')] : []
        const size = (el) => { const b = el.getBoundingClientRect(); return { w: Math.round(b.width), h: Math.round(b.height) } }
        const cs = labels[0] ? getComputedStyle(labels[0]) : null
        return {
          有打印照片: !!fig,
          打印时可见: fig ? getComputedStyle(fig).display !== 'none' : null,
          图片尺寸: img ? size(img) : null,
          图片已加载: img ? img.naturalWidth > 0 : null,
          打印单里的框数: fig ? fig.querySelectorAll('.det-box').length : 0,
          标签底色: cs ? cs.backgroundColor : null,
          标签字色: cs ? cs.color : null,
          顶栏已隐藏: getComputedStyle(document.querySelector('.term-topbar')).display === 'none',
          取景区已隐藏: getComputedStyle(document.querySelector('.photo-panel')).display === 'none',
        }
      })()`,
    )
    await cdp.send('Emulation.setEmulatedMedia', { media: '' })
    console.log('\n=== 打印媒体审计 ===')
    console.log(JSON.stringify(printAudit, null, 2))

    /** 从检测页返回首页，再点指定关键词的功能卡，进到目标子页 */
    const gotoCard = async (keyword) => {
      await evaluate(
        cdp,
        `(() => { const b = document.querySelector('.page-head .ag-btn'); if (b) b.click(); return 'back' })()`,
      )
      await sleep(1200)
      const r = await evaluate(
        cdp,
        `(() => {
          const cards = [...document.querySelectorAll('.feature-card')]
          const t = cards.find(c => new RegExp(${JSON.stringify(keyword)}).test(c.textContent || ''))
          if (!t) return 'FAIL'
          t.click(); return 'OK'
        })()`,
      )
      await sleep(1800)
      return r
    }

    /** 滚动区健康度：这是"内容超出但滚不动"这类问题的直接判据 */
    const SCROLL_AUDIT = `(() => {
      const sc = document.scrollingElement
      const rows = [...document.querySelectorAll('.record-item, .panel')]
      const list = document.querySelector('.record-list')
      const grid = document.querySelector('.board-grid')
      const info = (el) => el ? {
        h: Math.round(el.getBoundingClientRect().height),
        内容高: el.scrollHeight,
        可视高: el.clientHeight,
        是否可滚: el.scrollHeight > el.clientHeight + 1,
        溢出样式: getComputedStyle(el).overflowY,
      } : null
      return {
        viewport: window.innerWidth + 'x' + window.innerHeight,
        页面滚动: sc.scrollHeight > sc.clientHeight + 1,
        条目数: rows.length,
        条目最高底部: rows.length ? Math.round(Math.max(...rows.map(r => r.getBoundingClientRect().bottom))) : null,
        recordList: info(list),
        boardGrid: info(grid),
      }
    })()`

    // 先造一条问答记录。不造的话问答页签是空的，下面"点击问答行不报错"的断言
    // 会因为没有行而空过（假通过）—— 第一版就是这么漏掉的。
    console.log('\n=== 农事顾问：造一条问答记录 ===')
    console.log('进入：', await gotoCard('农事'))
    // 流式验证：用 MutationObserver 数气泡内容"变了几次"。
    // 为什么不按时间判：智谱免费档的首字延迟实测在 0.4s~几十秒之间波动，
    // 用"1.2 秒内必须出字"会把上游排队误判成"前端不是流式"。
    // 而"整段返回"只会让 DOM 变 1 次，"逐字追加"会变很多次 —— 这个判据与网速无关。
    const streaming = await evaluate(
      cdp,
      `(async () => {
        const q = document.querySelector('.quick-ask')
        if (!q) return { ok: false, reason: '没有快捷提问按钮' }
        q.click()
        await new Promise((r) => setTimeout(r, 150))
        const list = document.querySelectorAll('.msg.ai .bubble')
        const bubble = list.length ? list[list.length - 1] : null
        if (!bubble) return { ok: false, reason: '没有 AI 气泡' }
        let changes = 0
        let lastLen = -1
        const obs = new MutationObserver(() => {
          const len = bubble.innerText.length
          if (len !== lastLen) { changes += 1; lastLen = len }
        })
        obs.observe(bubble, { childList: true, characterData: true, subtree: true })
        const typingAtStart = !!bubble.querySelector('.typing')
        // 最多等 25 秒；一旦"有内容且光标消失"就说明流结束了，立即收工
        for (let i = 0; i < 50; i++) {
          await new Promise((r) => setTimeout(r, 500))
          if (bubble.innerText.length > 0 && !bubble.querySelector('.caret')) break
        }
        obs.disconnect()
        return {
          ok: true,
          changes,
          typingAtStart,
          finalLen: bubble.innerText.length,
          caretLeft: !!bubble.querySelector('.caret'),
        }
      })()`,
    )
    console.log('流式：', JSON.stringify(streaming))

    console.log('\n=== 历史记录页 ===')
    console.log('进入：', await gotoCard('历史'))
    const history = await evaluate(cdp, SCROLL_AUDIT)
    console.log(JSON.stringify(history, null, 2))

    // 滚动实测：滚到底，确认"真的滚得动"且页头吸顶生效。
    // 只看 CSS 判断不出来 —— 内容正好等于可视高时，有没有滚动条都不报错。
    const historyScroll = await evaluate(
      cdp,
      `(() => {
        const main = document.querySelector('.term-main')
        const head = document.querySelector('.page-head')
        if (!main) return { 有主区域: false }
        const before = main.scrollTop
        main.scrollTop = 99999
        const after = main.scrollTop
        const mr = main.getBoundingClientRect()
        const hr = head ? head.getBoundingClientRect() : null
        return {
          可滚动距离: main.scrollHeight - main.clientHeight,
          实际滚到: Math.round(after),
          滚动生效: after > before,
          // 吸顶量：页面用 sticky top:0，但滚动容器有 padding 时，
          // 吸顶位置会跟着 padding 走（页头下方会露出滚动内容）。这两个值用于定位。
          主区域内边距: getComputedStyle(main).paddingTop,
          主区域顶部: Math.round(mr.top),
          页头顶部: hr ? Math.round(hr.top) : null,
          吸顶偏移: hr ? Math.round(hr.top - mr.top) : null,
          页头吸顶: hr ? Math.abs(hr.top - mr.top) < 24 : null,
          页头top: hr ? Math.round(hr.top) : null,
          主区域top: Math.round(mr.top),
        }
      })()`,
    )
    console.log('\n=== 历史页滚动实测 ===')
    console.log(JSON.stringify(historyScroll, null, 2))

    // 问答页签不该出现「详情」按钮：它请求的 /api/history/{record_no} 只有检测记录存在，
    // 拿问答编号去查必然 404（用户实际遇到的报错）。这里直接数按钮。
    const chatTab = await evaluate(
      cdp,
      `(async () => {
        const segs = [...document.querySelectorAll('.seg button')]
        const chat = segs.find((b) => /问答|Q&A|سۇئال/.test(b.textContent || ''))
        if (!chat) return { 有页签: false }
        chat.click()
        await new Promise((r) => setTimeout(r, 1500))
        // 关键回归：问答行整行可点（@click=toggleDetail），点它会请求
        // /api/history/{record_no}，而问答记录没有 record_no → /api/history/undefined 404。
        // 直接拦 XHR 看点击后到底请求了什么（axios 在浏览器走 XHR，不是 fetch）。
        const urls = []
        const Orig = window.XMLHttpRequest
        const origOpen = Orig.prototype.open
        Orig.prototype.open = function (m, u) { urls.push(String(u)); return origOpen.apply(this, arguments) }
        const rows = [...document.querySelectorAll('.record-open')]
        rows.forEach((r) => r.click())
        await new Promise((r) => setTimeout(r, 1800))
        Orig.prototype.open = origOpen
        const histUrls = urls.filter((u) => u.includes('/api/history'))
        const labels = [...document.querySelectorAll('.record-btn')].map((b) => (b.textContent || '').trim())
        return {
          有页签: true,
          行数: rows.length,
          详情按钮数: labels.filter((t) => /详情|Detail/.test(t)).length,
          打印按钮数: labels.filter((t) => /打印|Print/.test(t)).length,
          点击后的历史请求: histUrls,
          请求含undefined: histUrls.some((u) => u.includes('undefined')),
        }
      })()`,
    )
    console.log('\n=== 问答页签 ===')
    console.log(JSON.stringify(chatTab, null, 2))

    console.log('\n=== 数据看板页 ===')
    console.log('进入：', await gotoCard('看板'))
    const board = await evaluate(cdp, SCROLL_AUDIT)
    console.log(JSON.stringify(board, null, 2))

    // 看板改成个人视角后的实测：KPI/图表是否渲染、内容超出时内层容器是否真滚得动、
    // 以及滚动是否只发生在内层容器（整页不滚，页头才能保持吸顶）。
    const BOARD_AUDIT = `(() => {
      const grid = document.querySelector('.board-grid')
      const main = document.querySelector('.term-main')
      const sc = document.scrollingElement
      const kpis = [...document.querySelectorAll('.kpi')]
      const panels = [...document.querySelectorAll('.board-grid .panel')]
      const empties = [...document.querySelectorAll('.board-empty')]
      const bars = [...document.querySelectorAll('.board-grid .bar')]
      const issues = [...document.querySelectorAll('.issue-row')]
      const arcs = [...document.querySelectorAll('.donut circle')]
      const info = grid ? {
        h: Math.round(grid.getBoundingClientRect().height),
        内容高: grid.scrollHeight,
        可视高: grid.clientHeight,
        是否可滚: grid.scrollHeight > grid.clientHeight + 1,
        溢出样式: getComputedStyle(grid).overflowY,
      } : null
      // 真正设一次 scrollTop，确认"能滚"而不是只有滚动条
      const before = grid ? grid.scrollTop : 0
      if (grid) grid.scrollTop = 99999
      const after = grid ? grid.scrollTop : 0
      const dist = grid ? grid.scrollHeight - grid.clientHeight : 0
      if (grid) grid.scrollTop = 0
      return {
        viewport: window.innerWidth + 'x' + window.innerHeight,
        grid: info,
        可滚动距离: dist,
        实际滚到: Math.round(after),
        滚动生效: after > before,
        页面滚动: sc.scrollHeight > sc.clientHeight + 1,
        主区域可滚: main ? main.scrollHeight > main.clientHeight + 1 : null,
        KPI数: kpis.length,
        面板数: panels.length,
        空状态数: empties.length,
        柱数: bars.length,
        问题行数: issues.length,
        环形段数: arcs.length,
        KPI文本: kpis.map((k) => ((k.querySelector('.kpi-value') || {}).textContent || '').trim()),
      }
    })()`

    console.log('\n=== 看板（个人视角）实测 ===')
    const boardAudit = await evaluate(cdp, BOARD_AUDIT)
    console.log(JSON.stringify(boardAudit, null, 2))

    // 强制一个矮视口，逼出"内容超出可视区"的场景，直接验证内层容器能不能滚。
    // 高度 600 刻意大于媒体查询阈值(560)：否则会走"整页滚动"的兜底分支，量不到真实行为。
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 1920,
      height: 600,
      deviceScaleFactor: 1,
      mobile: false,
    })
    await sleep(700)
    const boardShort = await evaluate(cdp, BOARD_AUDIT)
    console.log('\n=== 看板（矮视口 600）===')
    console.log(JSON.stringify(boardShort, null, 2))
    await cdp.send('Emulation.clearDeviceMetricsOverride')
    await sleep(700)

    // ---------- 游客模式：历史/看板必须上锁 ----------
    console.log('\n=== 游客模式锁定检查 ===')
    console.log('登出：', await logout())
    console.log('游客登录：', await guestEnter())
    const guestBefore = await evaluate(cdp, `location.pathname`)
    const guestLock = await evaluate(
      cdp,
      `(() => {
        const cards = [...document.querySelectorAll('.feature-card')]
        const locked = cards.filter((c) => c.classList.contains('is-locked'))
        const goOf = (c) => { const g = c.querySelector('.feature-go'); return g ? g.textContent.trim() : '' }
        const before = locked[0]
        const pathBefore = location.pathname
        if (before) before.click()
        return {
          卡片总数: cards.length,
          锁定卡数: locked.length,
          锁定卡标题: locked.map((c) => (c.querySelector('.feature-title') || {}).textContent || ''),
          锁定卡的按钮文案: locked.map(goOf),
          未锁卡的按钮文案: cards.filter((c) => !c.classList.contains('is-locked')).map(goOf),
          点击前路径: pathBefore,
        }
      })()`,
    )
    await sleep(900)
    const guestAfter = await evaluate(cdp, `location.pathname`)
    guestLock.点击后路径 = guestAfter
    guestLock.未跳转 = guestBefore === guestAfter
    console.log(JSON.stringify(guestLock, null, 2))

    // 维吾尔语字体：不仅要看 --k-font 链里有没有，还要确认字体文件真的加载上了
    const fontAudit = await evaluate(
      cdp,
      `(async () => {
        const sel = document.querySelector('.lang-select')
        if (!sel) return { 有下拉: false }
        sel.value = 'ug-CN'
        sel.dispatchEvent(new Event('change', { bubbles: true }))
        await new Promise((r) => setTimeout(r, 700))
        let faces = []
        if (document.fonts && document.fonts.load) {
          try { faces = await document.fonts.load('20px "ALKATIP Basma Tom"') } catch (e) { faces = [] }
        }
        return {
          切换后根节点语言: document.documentElement.getAttribute('lang'),
          根字体链: getComputedStyle(document.documentElement).getPropertyValue('--k-font').trim(),
          字体文件已加载: document.fonts ? document.fonts.check('20px "ALKATIP Basma Tom"') : null,
          加载到的字面数: faces.length,
          body实际字体: getComputedStyle(document.body).fontFamily.slice(0, 60),
          // 游客的名字必须跟着语言走，不能是后端硬编码的「游客-XXXX」
          游客显示名: (() => {
            const el = document.querySelector('.user-name')
            return el ? el.textContent.trim() : null
          })(),
          游客名含汉字: (() => {
            const el = document.querySelector('.user-name')
            return el ? /[\u4e00-\u9fff]/.test(el.textContent) : null
          })(),
        }
      })()`,
    )
    console.log('\n=== 维吾尔语字体 ===')
    console.log(JSON.stringify(fontAudit, null, 2))

    // 断言式结论，方便一眼看是否合格。
    // 注意：结果态里左侧的 .upload-box 已被 .preview-wrap 取代，所以看图片盒要判断 previewWrap。
    const vh = Number(after.viewport.split('x')[1])
    const homeVh = Number(home.viewport.split('x')[1])
    const checks = [
      ['首页四张卡都在视口内', home.卡片数 === 4 && home.最低卡片底部 !== null && home.最低卡片底部 <= homeVh + 1],
      ['首页整页不滚动', home.页面滚动 === false],
      [
        '首页四张卡的插画都已加载',
        art.插画地址.length === 4 && art.插画地址.every(Boolean) && art.插画是否加载成功.every(Boolean),
      ],
      ['取景态：上传框在视口内', pick.uploadBox !== null && pick.uploadBox.bottom <= vh + 1],
      ['取景态：整页不滚动', pick.页面滚动 === false],
      ['结果态：左侧图片盒在视口内', after.previewWrap !== null && after.previewWrap.bottom <= vh + 1],
      ['结果态：右侧报告区内部可滚动', after.报告内部可滚 === true],
      ['结果态：整页不滚动（滚动交给报告区）', after.页面滚动 === false],
      ['页头高度 ≤ 60px', after.pageHead !== null && after.pageHead.h <= 60],
      ['报告区吃满分栏剩余高度', after.reportScroll !== null && after.reportPanel !== null && after.reportScroll.h >= after.reportPanel.h - 110],
      // 历史页：设计上列表不再自己滚（overflow: visible），改由 .term-main 承担整页滚动
      ['历史页：列表不再被压成一屏高', history.recordList === null || history.recordList.溢出样式 === 'visible'],
      ['看板页：面板未溢出视口或网格可滚',
        board.boardGrid === null ||
        board.条目最高底部 <= Number(board.viewport.split('x')[1]) + 1 ||
        board.boardGrid.是否可滚 === true],
      // 看板（个人视角）：KPI 与图表必须真的渲染出来（或给出空状态），不能是空框
      ['看板：KPI 与图表节点已渲染',
        boardAudit.KPI数 === 4 && boardAudit.面板数 === 3 &&
        (boardAudit.柱数 > 0 || boardAudit.问题行数 > 0 || boardAudit.环形段数 > 0 || boardAudit.空状态数 > 0)],
      ['看板：内容容器是可滚动区（overflow-y: auto）',
        boardAudit.grid !== null && boardAudit.grid.溢出样式 === 'auto'],
      ['看板：内容超出时容器滚得动',
        boardAudit.grid === null || boardAudit.grid.是否可滚 === false || boardAudit.滚动生效 === true],
      ['看板：整页不滚动（滚动只在内层容器）',
        boardAudit.页面滚动 === false && boardAudit.主区域可滚 === false],
      // 矮视口逼出溢出，直接证明"超出时必须滚得动"
      ['看板：矮视口下内容确实超出可视区',
        boardShort.grid !== null && boardShort.grid.是否可滚 === true && boardShort.可滚动距离 > 0],
      ['看板：矮视口下内层容器真的滚得动', boardShort.滚动生效 === true],
      ['看板：矮视口下整页仍不滚动',
        boardShort.页面滚动 === false && boardShort.主区域可滚 === false],
      // 历史页：内容超出时必须真的滚得动（内容放得下则视为通过）
      ['历史页：内容超出时滚得动', historyScroll.可滚动距离 <= 0 || historyScroll.滚动生效 === true],
      ['历史页：滚动后页头吸顶', historyScroll.可滚动距离 <= 0 || historyScroll.页头吸顶 === true],
      // 问答行若还能点出详情，就会打 /api/history/{问答编号} 并 404。
      // 必须要求 行数 > 0，否则空列表下断言会假通过。
      // 整段返回只会让 DOM 变 1 次；逐字追加会变很多次。
      // 这个判据不依赖上游快慢，所以不会因为免费档排队而假失败。
      ['问答：回答是逐字追加的（内容多次变化）', streaming.ok === true && streaming.changes >= 5],
      ['问答：最终拿到了完整回答', streaming.ok === true && streaming.finalLen > 20],
      ['问答：流结束后光标已移除', streaming.ok === true && streaming.caretLeft === false],
      ['问答页签：点整行不再打 /api/history/undefined',
        chatTab.有页签 === true && chatTab.行数 > 0 &&
        chatTab.请求含undefined === false && chatTab.详情按钮数 === 0],
      // 检测框：这是用户明确要求的"画框 + 中文标签 + 置信度"
      ['检测框：图层叠加在图片上', boxAudit.有图层 === true],
      ['检测框：图层与图片严格对齐', boxAudit.图层与图片对齐 === true],
      ['检测框：至少画出一个框', (boxAudit.框数 || 0) > 0],
      ['检测框：框都在图片范围内', boxAudit.框都在图片范围内 === true],
      ['检测框：标签是中文', boxAudit.标签含中文 === true],
      ['检测框：标签带置信度百分比', boxAudit.标签含置信度 === true],
      ['检测框：标签可见未被裁', boxAudit.标签可见 === true],
      // 登录页：语言选择要在「进入系统 + 说明」之后
      ['登录页：语言选择在标题与说明下方',
        loginLayout.有登录卡 === true &&
        loginLayout.语言选择在标题下方 === true &&
        loginLayout.语言选择在说明下方 === true],
      ['登录页：卡片毛玻璃已生效', loginLayout.毛玻璃已生效 === true],
      ['登录页：卡片内容未被裁', loginLayout.卡片内容未溢出 === true],
      // 后端错误提示必须按 code 本地化，不能把中文原样显示给少数民族用户
      ['报错文案：维语下不含汉字', errorI18n.有下拉 === true && errorI18n.报错含汉字 === false && errorI18n.时长 > 0],
      // 维吾尔语字体：链里要有，文件也要真加载上
      ['维语：根字体链已切到 ALKATIP', /ALKATIP/i.test(fontAudit.根字体链 || '')],
      ['维语：字体文件已加载', fontAudit.字体文件已加载 === true],
      ['维语：根节点 lang 已切换', fontAudit.切换后根节点语言 === 'ug-CN'],
      ['维语：游客名字没有残留中文', fontAudit.游客名含汉字 === false && !!fontAudit.游客显示名],
      // 游客模式：不限功能，但历史与看板上锁
      ['游客模式：历史与看板两张卡被锁', guestLock.锁定卡数 === 2],
      ['游客模式：锁定卡显示"游客不可用"',
        (guestLock.锁定卡的按钮文案 || []).length === 2 &&
        guestLock.锁定卡的按钮文案.every((t) => /游客不可用|Login required/.test(t))],
      ['游客模式：识别与问答仍可用', (guestLock.未锁卡的按钮文案 || []).length === 2],
      ['游客模式：点击锁定卡不跳转', guestLock.未跳转 === true],
      // 打印单：必须带上上传的照片，且标签要黑白化（彩打/灰度都要能看清）
      ['打印单：包含上传的照片', printAudit.有打印照片 === true && printAudit.打印时可见 === true],
      ['打印单：照片有实际尺寸且已加载',
        !!printAudit.图片尺寸 && printAudit.图片尺寸.w > 50 && printAudit.图片尺寸.h > 50 && printAudit.图片已加载 === true],
      ['打印单：照片上带检测框', printAudit.打印单里的框数 > 0],
      ['打印单：标签改为白底黑字', printAudit.标签底色 === 'rgb(255, 255, 255)' && printAudit.标签字色 === 'rgb(0, 0, 0)'],
      ['打印单：顶栏与取景区已隐藏', printAudit.顶栏已隐藏 === true && printAudit.取景区已隐藏 === true],
    ]
    console.log('\n=== 结论 ===')
    for (const [name, ok] of checks) {
      console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}`)
      if (!ok) failed = true
    }
  } catch (e) {
    console.error('实测失败：', e.message)
    failed = true
  } finally {
    if (cdp) cdp.close()
    chrome.kill()
    await sleep(400)
    try {
      fs.rmSync(profile, { recursive: true, force: true })
    } catch {
      /* 清理失败不影响结论 */
    }
  }
  process.exit(failed ? 1 : 0)
}

main()
