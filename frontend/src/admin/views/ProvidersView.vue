<script setup>
/**
 * 大模型厂商配置。
 *
 * 关键约定（必须写清楚，否则会误操作）：
 * - 后端只返回掩码 api_key_masked，永不返回完整密钥；
 * - 提交时"api_key 留空 = 不修改"——因此编辑态只在用户真的输入了内容时才
 *   把 api_key 放进 PATCH 请求体（空串会被后端当成有效值覆盖掉原密钥）。
 * - 勾选"设为默认"后，后端会自动把其它厂商的 is_default 置 false。
 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { providerApi } from '@admin/api'

const KNOWN_PROVIDERS = [
  { value: 'zhipu', label: '智谱 AI' },
  { value: 'qwen', label: '通义千问' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'moonshot', label: 'Moonshot' },
  { value: 'baidu', label: '百度文心' },
  { value: 'custom', label: '自定义' },
]

const loading = ref(false)
const rows = ref([])
const testing = ref('')

const dialogVisible = ref(false)
const saving = ref(false)
const formRef = ref(null)
const mode = ref('create')
const form = reactive({
  provider: '',
  label: '',
  base_url: '',
  model: '',
  api_key: '',
  enabled: true,
  is_default: false,
})

const dialogTitle = ref('新增厂商')

const rules = {
  provider: [{ required: true, message: '请选择或输入 provider 标识', trigger: 'change' }],
  base_url: [{ required: true, message: '请输入 base_url', trigger: 'blur' }],
  model: [{ required: true, message: '请输入模型名', trigger: 'blur' }],
}

async function load() {
  loading.value = true
  try {
    rows.value = (await providerApi.list()) || []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  mode.value = 'create'
  dialogTitle.value = '新增厂商'
  Object.assign(form, { provider: '', label: '', base_url: '', model: '', api_key: '', enabled: true, is_default: false })
  dialogVisible.value = true
}

function openEdit(row) {
  mode.value = 'edit'
  dialogTitle.value = `编辑配置 · ${row.label || row.provider}`
  Object.assign(form, {
    provider: row.provider,
    label: row.label || '',
    base_url: row.base_url || '',
    model: row.model || '',
    api_key: '', // 始终留空：留空即不修改
    enabled: Boolean(row.enabled),
    is_default: Boolean(row.is_default),
  })
  dialogVisible.value = true
}

async function onSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    if (mode.value === 'create') {
      await providerApi.create({ ...form })
      ElMessage.success('厂商配置已创建')
    } else {
      const payload = {
        label: form.label,
        base_url: form.base_url,
        model: form.model,
        enabled: form.enabled,
        is_default: form.is_default,
      }
      if (form.api_key) payload.api_key = form.api_key
      await providerApi.update(form.provider, payload)
      ElMessage.success('厂商配置已更新')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function onToggleEnabled(row) {
  try {
    await providerApi.update(row.provider, { enabled: row.enabled })
    ElMessage.success(`${row.label || row.provider} 已${row.enabled ? '启用' : '停用'}`)
  } catch {
    row.enabled = !row.enabled // 失败回滚开关状态
  }
}

async function onSetDefault(row) {
  await providerApi.update(row.provider, { is_default: true })
  ElMessage.success(`已将「${row.label || row.provider}」设为默认厂商`)
  load()
}

async function onTest(row) {
  testing.value = row.provider
  try {
    const res = await providerApi.test(row.provider)
    const detail = `${res.model || row.model} · ${res.latency_ms}ms`
    if (res.ok) ElMessage.success(`${res.message || '连接正常'}（${detail}）`)
    else ElMessage.warning(`${res.message || '连接失败'}（${detail}）`)
  } finally {
    testing.value = ''
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`确定删除厂商「${row.label || row.provider}」的配置吗？`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  const res = await providerApi.remove(row.provider)
  ElMessage.success(res.message || '已删除')
  load()
}

function formatTime(value) {
  return value ? value.replace('T', ' ').slice(0, 19) : '—'
}

onMounted(load)
</script>

<template>
  <div class="admin-page">
    <div class="page-head">
      <div>
        <h2 class="page-title">大模型配置</h2>
        <p class="page-sub">管理问答服务使用的大模型厂商与密钥（密钥仅以掩码展示）</p>
      </div>
      <div>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新增厂商</el-button>
      </div>
    </div>

    <el-alert class="tip" type="info" :closable="false" show-icon>
      <template #title>
        编辑时 <b>API Key 留空表示不修改</b>当前密钥；只有填写了新值才会覆盖。勾选"设为默认"会自动取消其它厂商的默认状态。
      </template>
    </el-alert>

    <div class="table-wrap">
      <el-table v-loading="loading" :data="rows" style="width: 100%">
        <el-table-column label="厂商" min-width="150">
          <template #default="{ row }">
            <div class="provider-cell">
              <span class="provider-label">{{ row.label || row.provider }}</span>
              <span class="provider-code">{{ row.provider }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="model" label="模型" min-width="150" show-overflow-tooltip />
        <el-table-column prop="base_url" label="Base URL" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.base_url || '—' }}</template>
        </el-table-column>
        <el-table-column label="API Key" min-width="170">
          <template #default="{ row }">
            <span class="mono">{{ row.api_key_masked || '未配置' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.configured ? 'success' : 'info'" effect="plain">
              {{ row.configured ? '已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" @change="onToggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column label="默认" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.is_default" size="small" type="success" effect="dark">默认</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" min-width="170">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :loading="testing === row.provider" @click="onTest(row)">测试</el-button>
            <el-button link type="primary" :disabled="row.is_default" @click="onSetDefault(row)">设为默认</el-button>
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无厂商配置" :image-size="90" />
        </template>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="560px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
        <el-form-item label="厂商标识" prop="provider">
          <el-select
            v-model="form.provider"
            filterable
            allow-create
            default-first-option
            :disabled="mode === 'edit'"
            placeholder="选择或输入，如 zhipu / qwen / custom"
            style="width: 100%"
          >
            <el-option v-for="p in KNOWN_PROVIDERS" :key="p.value" :label="`${p.label}（${p.value}）`" :value="p.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="显示名称" prop="label">
          <el-input v-model="form.label" placeholder="如：智谱 AI" />
        </el-form-item>
        <el-form-item label="Base URL" prop="base_url">
          <el-input v-model="form.base_url" placeholder="https://..." />
        </el-form-item>
        <el-form-item label="模型" prop="model">
          <el-input v-model="form.model" placeholder="如：glm-4-flash" />
        </el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="form.api_key"
            type="password"
            autocomplete="new-password"
            show-password
            :placeholder="mode === 'edit' ? '留空表示不修改当前密钥' : '请输入密钥'"
          />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="form.is_default" />
          <span class="form-hint">开启后会自动取消其它厂商的默认状态</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.tip {
  margin-bottom: 16px;
}

.provider-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.35;
}

.provider-label {
  font-weight: 500;
}

.provider-code {
  font-size: 12px;
  color: var(--admin-text-weak);
}

.mono {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 13px;
}

.muted {
  color: var(--admin-text-weak);
}

.form-hint {
  margin-left: 12px;
  font-size: 12px;
  color: var(--admin-text-weak);
}
</style>
