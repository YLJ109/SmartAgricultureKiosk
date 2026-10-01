<script setup>
/**
 * 多语言资源：在不改代码的情况下覆盖前端内置词条。
 *
 * 后端 PUT /admin/lang-resources 是按 (lang, key) upsert 的，所以编辑态要锁定
 * 语言与 key——否则改 key 会变成"新增一条"而不是"修改这条"。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Refresh } from '@element-plus/icons-vue'
import { langApi } from '@admin/api'

const LANG_OPTIONS = [
  { value: 'zh-CN', label: '简体中文' },
  { value: 'en-US', label: '英语' },
  { value: 'ug-CN', label: '维吾尔语' },
  { value: 'kk-CN', label: '哈萨克语' },
  { value: 'bo-CN', label: '藏语' },
  { value: 'mn-CN', label: '蒙古语' },
]

const LANG_LABEL = Object.fromEntries(LANG_OPTIONS.map((l) => [l.value, l.label]))

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 20, lang: '', keyword: '' })

const dialogVisible = ref(false)
const saving = ref(false)
const formRef = ref(null)
const mode = ref('create')
const form = reactive({ lang: 'zh-CN', key: '', value: '' })

const dialogTitle = computed(() => (mode.value === 'edit' ? '编辑词条' : '新增词条'))

const rules = {
  lang: [{ required: true, message: '请选择语言', trigger: 'change' }],
  key: [
    { required: true, message: '请输入词条 key', trigger: 'blur' },
    { max: 128, message: 'key 最长 128 个字符', trigger: 'blur' },
  ],
  value: [{ required: true, message: '请输入词条内容', trigger: 'blur' }],
}

async function load() {
  loading.value = true
  try {
    const res = await langApi.list({
      page: query.page,
      page_size: query.page_size,
      lang: query.lang || undefined,
      keyword: query.keyword || undefined,
    })
    rows.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

function onSearch() {
  query.page = 1
  load()
}

function onReset() {
  query.lang = ''
  query.keyword = ''
  query.page = 1
  load()
}

function onPageChange(page) {
  query.page = page
  load()
}

function openCreate() {
  mode.value = 'create'
  Object.assign(form, { lang: 'zh-CN', key: '', value: '' })
  dialogVisible.value = true
}

function openEdit(row) {
  mode.value = 'edit'
  Object.assign(form, { lang: row.lang, key: row.key, value: row.value })
  dialogVisible.value = true
}

async function onSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    await langApi.upsert({ ...form })
    ElMessage.success(mode.value === 'edit' ? '词条已更新' : '词条已保存')
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`确定删除词条「${row.lang}:${row.key}」吗？`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  const res = await langApi.remove(row.id)
  ElMessage.success(res.message || '已删除')
  // 删掉当前页最后一条时回退一页，避免停留在空白页
  if (rows.value.length === 1 && query.page > 1) query.page -= 1
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
        <h2 class="page-title">多语言资源</h2>
        <p class="page-sub">覆盖前端内置词条，无需改代码即可调整各语言文案</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新增词条</el-button>
    </div>

    <div class="filter-bar">
      <el-select v-model="query.lang" placeholder="全部语言" clearable>
        <el-option v-for="l in LANG_OPTIONS" :key="l.value" :label="l.label" :value="l.value" />
      </el-select>
      <el-input v-model="query.keyword" placeholder="key / 词条内容" clearable :prefix-icon="Search" @keyup.enter="onSearch" />
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button :icon="Refresh" @click="onReset">重置</el-button>
    </div>

    <div class="table-wrap">
      <el-table v-loading="loading" :data="rows" style="width: 100%">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="语言" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ LANG_LABEL[row.lang] || row.lang }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="key" label="词条 KEY" min-width="200" show-overflow-tooltip />
        <el-table-column prop="value" label="内容" min-width="260" show-overflow-tooltip />
        <el-table-column label="更新时间" min-width="170">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无词条，点击右上角新增" :image-size="90" />
        </template>
      </el-table>

      <div class="table-pager">
        <el-pagination
          layout="total, prev, pager, next"
          :total="total"
          :current-page="query.page"
          :page-size="query.page_size"
          @current-change="onPageChange"
        />
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="520px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="88px">
        <el-form-item label="语言" prop="lang">
          <el-select v-model="form.lang" :disabled="mode === 'edit'" style="width: 100%">
            <el-option v-for="l in LANG_OPTIONS" :key="l.value" :label="l.label" :value="l.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="KEY" prop="key">
          <el-input v-model="form.key" :disabled="mode === 'edit'" placeholder="如：home.title" />
        </el-form-item>
        <el-form-item label="内容" prop="value">
          <el-input v-model="form.value" type="textarea" :rows="3" placeholder="该语言下的展示文案" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
