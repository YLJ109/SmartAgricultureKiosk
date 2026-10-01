<script setup>
/**
 * 数据看板。
 *
 * 注意后端 /admin/dashboard 的返回结构是 { overview: {...统计字段}, provider_configs,
 * recent_logs, knowledge }——统计字段是嵌套在 overview 下的，不是平铺。这里做了
 * 兼容（dash.overview || dash），平铺与嵌套都能渲染。
 *
 * 图表全部手写 SVG / CSS，不引 echarts：需求明确不新增依赖，且看板图形很简单。
 */
import { computed, onMounted, ref } from 'vue'
import { dashboardApi } from '@admin/api'

const loading = ref(true)
const overview = ref({})
const providers = ref([])
const recentLogs = ref([])
const knowledge = ref({})
const trend = ref([])
const disease = ref([])
const regions = ref([])
const questions = ref([])

const kpis = computed(() => {
  const o = overview.value
  return [
    { key: 'detection', label: '检测总量', value: o.detection_total ?? 0, sub: `今日 +${o.detection_today ?? 0}`, accent: '#2e9e4f' },
    { key: 'users', label: '注册用户', value: o.users_total ?? 0, sub: `不含游客`, accent: '#1a73e8' },
    { key: 'chat', label: '问答量', value: o.chat_total ?? 0, sub: `今日 +${o.chat_today ?? 0}`, accent: '#0f8f8f' },
    { key: 'rate', label: '识别命中率', value: `${o.identified_rate ?? 0}%`, sub: `平均置信度 ${o.avg_confidence ?? 0}%`, accent: '#e59500' },
  ]
})

// 趋势折线：把 points 算成 SVG path，viewBox 固定 0 0 680 240
const trendChart = computed(() => {
  const data = trend.value
  if (!data.length) return null
  const W = 680
  const H = 240
  const padX = 34
  const padY = 24
  const max = Math.max(...data.map((d) => d.value), 1)
  const stepX = data.length > 1 ? (W - padX * 2) / (data.length - 1) : 0

  const points = data.map((d, i) => ({
    x: padX + i * stepX,
    y: H - padY - (d.value / max) * (H - padY * 2),
  }))
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  const last = points[points.length - 1]
  const first = points[0]
  const area = `${line} L${last.x.toFixed(1)},${H - padY} L${first.x.toFixed(1)},${H - padY} Z`

  const yTicks = [1, 0.5, 0].map((t) => ({
    y: H - padY - t * (H - padY * 2),
    label: Math.round(max * t),
  }))
  // 只标首/中/末三个 X 轴标签，30 个点全标会糊成一团；去重避免单点数据时重复 key
  const xIndexes = [...new Set(data.length > 2 ? [0, Math.floor((data.length - 1) / 2), data.length - 1] : [0, data.length - 1])]

  return { W, H, line, area, points, yTicks, xLabels: xIndexes.map((i) => ({ x: points[i].x, text: data[i].label })) }
})

const maxDisease = computed(() => Math.max(...disease.value.map((d) => d.value), 1))
const maxRegion = computed(() => Math.max(...regions.value.map((d) => d.value), 1))
const maxQuestion = computed(() => Math.max(...questions.value.map((d) => d.c), 1))

const categoryLabels = {
  disease: '病害',
  pest: '虫害',
  nutrient: '缺素',
  phyto: '药害/胁迫',
  healthy: '未见异常',
  unknown: '未识别',
}

function toPercent(value, max) {
  return Math.round((value / max) * 100)
}

async function load() {
  loading.value = true
  try {
    const [dash, trendData, diseaseData, regionData, questionData] = await Promise.all([
      dashboardApi.dashboard(),
      dashboardApi.trend(30),
      dashboardApi.diseaseDist(8, 'zh-CN'),
      dashboardApi.regions(8),
      dashboardApi.topQuestions(8),
    ])
    overview.value = dash.overview || dash
    providers.value = dash.provider_configs || []
    recentLogs.value = dash.recent_logs || []
    knowledge.value = dash.knowledge || {}
    trend.value = trendData || []
    disease.value = diseaseData || []
    regions.value = regionData || []
    questions.value = questionData || []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="admin-page">
    <div class="page-head">
      <div>
        <h2 class="page-title">数据看板</h2>
        <p class="page-sub">检测、问答与用户运营概览 · 数据实时聚合自数据库</p>
      </div>
      <el-tag v-if="overview.provider_label" type="success" effect="plain">
        当前模型：{{ overview.provider_label }}
      </el-tag>
    </div>

    <!-- KPI -->
    <div class="kpi-grid">
      <div v-for="k in kpis" :key="k.key" class="kpi-card panel">
        <span class="kpi-bar" :style="{ background: k.accent }"></span>
        <div class="kpi-label">{{ k.label }}</div>
        <div class="kpi-value num">{{ typeof k.value === 'number' ? k.value.toLocaleString() : k.value }}</div>
        <div class="kpi-sub">{{ k.sub }}</div>
      </div>
    </div>

    <!-- 趋势 + 病害分布 -->
    <div class="grid-2">
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">检测趋势（近 30 天）</span>
        </div>
        <div class="panel-body">
          <svg v-if="trendChart" class="trend-svg" :viewBox="`0 0 ${trendChart.W} ${trendChart.H}`" preserveAspectRatio="none">
            <line
              v-for="t in trendChart.yTicks"
              :key="`y-${t.y}`"
              :x1="30"
              :x2="trendChart.W - 20"
              :y1="t.y"
              :y2="t.y"
              stroke="#eceff3"
              stroke-width="1"
            />
            <text v-for="t in trendChart.yTicks" :key="`yl-${t.y}`" :x="4" :y="t.y + 4" class="axis-text">{{ t.label }}</text>
            <path :d="trendChart.area" fill="rgba(46, 158, 79, 0.12)" />
            <path :d="trendChart.line" fill="none" stroke="#2e9e4f" stroke-width="2.5" stroke-linejoin="round" />
            <text v-for="l in trendChart.xLabels" :key="`xl-${l.x}`" :x="l.x" :y="trendChart.H - 6" class="axis-text" text-anchor="middle">
              {{ l.text }}
            </text>
          </svg>
          <el-empty v-else description="暂无检测数据" :image-size="90" />
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">病害分布</span>
          <span class="muted">按识别类别</span>
        </div>
        <div class="panel-body">
          <template v-if="disease.length">
            <div v-for="item in disease" :key="item.name" class="bar-row">
              <span class="bar-name" :title="item.name">{{ item.name }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: `${toPercent(item.value, maxDisease)}%`, background: item.color || '#2e9e4f' }"></div>
              </div>
              <span class="bar-value num">{{ item.value }}</span>
            </div>
          </template>
          <el-empty v-else description="暂无识别记录" :image-size="90" />
        </div>
      </div>
    </div>

    <!-- 地区分布 + 热门问题 -->
    <div class="grid-2">
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">地区分布</span>
          <span class="muted">按用户所属地区</span>
        </div>
        <div class="panel-body">
          <template v-if="regions.length">
            <div v-for="item in regions" :key="item.name" class="bar-row">
              <span class="bar-name" :title="item.name">{{ item.name }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: `${toPercent(item.value, maxRegion)}%`, background: '#1a73e8' }"></div>
              </div>
              <span class="bar-value num">{{ item.value }}</span>
            </div>
          </template>
          <el-empty v-else description="暂无地区数据" :image-size="90" />
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">热门问题</span>
          <span class="muted">Top {{ questions.length || 0 }}</span>
        </div>
        <div class="panel-body">
          <ol v-if="questions.length" class="question-list">
            <li v-for="(item, index) in questions" :key="item.q" class="question-item">
              <span class="question-rank" :class="{ top: index < 3 }">{{ index + 1 }}</span>
              <span class="question-text" :title="item.q">{{ item.q }}</span>
              <span class="question-count num">{{ item.c }} 次</span>
            </li>
          </ol>
          <el-empty v-else description="暂无问答记录" :image-size="90" />
        </div>
      </div>
    </div>

    <!-- 知识库 + 厂商状态 -->
    <div class="grid-2">
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">知识库概览</span>
        </div>
        <div class="panel-body">
          <div class="kv-grid">
            <div class="kv"><span class="kv-label">病虫害类别</span><span class="kv-value num">{{ knowledge.class_total ?? overview.class_total ?? 0 }}</span></div>
            <div class="kv"><span class="kv-label">支持作物</span><span class="kv-value num">{{ (knowledge.crops || []).length }}</span></div>
            <div class="kv"><span class="kv-label">语言数量</span><span class="kv-value num">{{ overview.lang_count ?? 0 }}</span></div>
            <div class="kv"><span class="kv-label">肥料养分项</span><span class="kv-value num">{{ knowledge.nutrient_total ?? 0 }}</span></div>
          </div>
          <div class="cat-tags">
            <el-tag v-for="(count, key) in knowledge.by_category || {}" :key="key" size="small" effect="plain" type="info">
              {{ categoryLabels[key] || key }} {{ count }}
            </el-tag>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">大模型厂商状态</span>
        </div>
        <div class="panel-body">
          <div v-for="p in providers" :key="p.provider" class="provider-row">
            <span class="provider-name">
              {{ p.label || p.provider }}
              <el-tag v-if="p.is_default" size="small" type="success" effect="dark">默认</el-tag>
            </span>
            <span class="provider-meta">
              <el-tag size="small" :type="p.configured ? 'success' : 'info'" effect="plain">
                {{ p.configured ? '已配置' : '未配置' }}
              </el-tag>
              <el-tag size="small" :type="p.enabled ? 'success' : 'warning'" effect="plain">
                {{ p.enabled ? '启用' : '停用' }}
              </el-tag>
            </span>
          </div>
          <el-empty v-if="!providers.length" description="暂无厂商配置" :image-size="80" />
        </div>
      </div>
    </div>

    <!-- 最近操作 -->
    <div class="panel log-panel">
      <div class="panel-head">
        <span class="panel-title">最近操作</span>
        <router-link class="muted link" to="/logs">查看全部</router-link>
      </div>
      <el-table :data="recentLogs" size="default" style="width: 100%">
        <el-table-column prop="created_at" label="时间" min-width="180">
          <template #default="{ row }">{{ (row.created_at || '').replace('T', ' ').slice(0, 19) }}</template>
        </el-table-column>
        <el-table-column prop="actor" label="操作人" width="140" />
        <el-table-column prop="action" label="动作" width="180" />
        <el-table-column prop="target" label="对象" min-width="140" show-overflow-tooltip />
        <el-table-column prop="detail" label="详情" min-width="200" show-overflow-tooltip />
        <template #empty>
          <el-empty description="暂无操作日志" :image-size="80" />
        </template>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.kpi-card {
  position: relative;
  padding: 18px 18px 16px 22px;
  overflow: hidden;
}

.kpi-bar {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
}

.kpi-label {
  font-size: 13px;
  color: var(--admin-text-weak);
}

.kpi-value {
  margin: 8px 0 6px;
  font-size: 28px;
  font-weight: 600;
  line-height: 1.1;
}

.kpi-sub {
  font-size: 12px;
  color: var(--admin-text-weak);
}

.grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.muted {
  font-size: 12px;
  color: var(--admin-text-weak);
}

.link {
  text-decoration: none;
  color: var(--admin-accent);
}

/* 折线图 */
.trend-svg {
  width: 100%;
  height: 240px;
  display: block;
}

.axis-text {
  font-size: 11px;
  fill: #9aa2ad;
}

/* 条形图 */
.bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.bar-name {
  width: 96px;
  flex: none;
  font-size: 13px;
  color: var(--admin-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bar-track {
  flex: 1;
  height: 12px;
  background: #f0f2f5;
  border-radius: 6px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 6px;
  transition: width 0.3s ease;
}

.bar-value {
  width: 44px;
  flex: none;
  text-align: right;
  font-size: 13px;
  color: var(--admin-text-weak);
}

/* 热门问题 */
.question-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.question-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px dashed var(--admin-border);
}

.question-item:last-child {
  border-bottom: none;
}

.question-rank {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex: none;
  border-radius: 6px;
  font-size: 12px;
  background: #eef1f5;
  color: var(--admin-text-weak);
}

.question-rank.top {
  background: #2e9e4f;
  color: #fff;
}

.question-text {
  flex: 1;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.question-count {
  flex: none;
  font-size: 12px;
  color: var(--admin-text-weak);
}

/* 知识库 */
.kv-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.kv {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.kv-label {
  font-size: 12px;
  color: var(--admin-text-weak);
}

.kv-value {
  font-size: 20px;
  font-weight: 600;
}

.cat-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* 厂商状态 */
.provider-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 0;
  border-bottom: 1px dashed var(--admin-border);
}

.provider-row:last-child {
  border-bottom: none;
}

.provider-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.provider-meta {
  display: flex;
  gap: 6px;
}

.log-panel {
  margin-bottom: 8px;
}

@media (max-width: 1180px) {
  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .grid-2 {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
