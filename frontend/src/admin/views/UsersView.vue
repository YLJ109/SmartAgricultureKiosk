<script setup>
/**
 * 用户管理：查询、新建、编辑、删除。
 *
 * 用户名后端 PATCH 不支持修改（UserPatch 里没有 username），所以编辑态禁用用户名，
 * 避免用户改了却保存不上的困惑。密码在编辑态留空即"不修改"。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Refresh } from '@element-plus/icons-vue'
import { userApi } from '@admin/api'

const ROLE_OPTIONS = [
  { value: 'farmer', label: '农户' },
  { value: 'guest', label: '游客' },
  { value: 'operator', label: '农技员' },
  { value: 'admin', label: '管理员' },
]

const LANG_OPTIONS = [
  { value: 'zh-CN', label: '简体中文' },
  { value: 'en-US', label: '英语' },
  { value: 'ug-CN', label: '维吾尔语' },
  { value: 'kk-CN', label: '哈萨克语' },
  { value: 'bo-CN', label: '藏语' },
  { value: 'mn-CN', label: '蒙古语' },
]

const ROLE_LABEL = Object.fromEntries(ROLE_OPTIONS.map((r) => [r.value, r.label]))
const LANG_LABEL = Object.fromEntries(LANG_OPTIONS.map((l) => [l.value, l.label]))
const ROLE_TAG = { admin: 'danger', operator: 'success', farmer: 'primary', guest: 'info' }

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 20, keyword: '', role: '' })

const dialogVisible = ref(false)
const saving = ref(false)
const formRef = ref(null)
const editingId = ref(null)
const form = reactive({
  username: '',
  password: '',
  display_name: '',
  phone: '',
  role: 'farmer',
  lang_pref: 'zh-CN',
  region: '',
  status: 'active',
})

const isEdit = computed(() => editingId.value !== null)
const dialogTitle = computed(() => (isEdit.value ? '编辑用户' : '新建用户'))

const rules = computed(() => ({
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 64, message: '长度 2-64 个字符', trigger: 'blur' },
  ],
  password: isEdit.value
    ? [{ min: 6, message: '密码至少 6 位', trigger: 'blur' }]
    : [
        { required: true, message: '请输入初始密码', trigger: 'blur' },
        { min: 6, message: '密码至少 6 位', trigger: 'blur' },
      ],
}))

async function load() {
  loading.value = true
  try {
    const res = await userApi.list({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      role: query.role || undefined,
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
  query.keyword = ''
  query.role = ''
  query.page = 1
  load()
}

function onPageChange(page) {
  query.page = page
  load()
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    username: '',
    password: '',
    display_name: '',
    phone: '',
    role: 'farmer',
    lang_pref: 'zh-CN',
    region: '',
    status: 'active',
  })
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    username: row.username,
    password: '',
    display_name: row.display_name || '',
    phone: row.phone || '',
    role: row.role,
    lang_pref: row.lang_pref || 'zh-CN',
    region: row.region || '',
    status: row.status || 'active',
  })
  dialogVisible.value = true
}

async function onSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    if (isEdit.value) {
      // 密码为空表示不修改，不把空串发给后端覆盖原密码
      const payload = {
        display_name: form.display_name,
        phone: form.phone,
        role: form.role,
        lang_pref: form.lang_pref,
        region: form.region,
        status: form.status,
      }
      if (form.password) payload.password = form.password
      await userApi.update(editingId.value, payload)
      ElMessage.success('用户已更新')
    } else {
      await userApi.create({ ...form })
      ElMessage.success('用户已创建')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`确定删除用户「${row.username}」吗？此操作不可恢复。`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  const res = await userApi.remove(row.id)
  ElMessage.success(res.message || '删除成功')
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
        <h2 class="page-title">用户管理</h2>
        <p class="page-sub">管理农户、农技员与管理员账号</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
    </div>

    <div class="filter-bar">
      <el-input v-model="query.keyword" placeholder="用户名 / 昵称 / 手机号" clearable :prefix-icon="Search" @keyup.enter="onSearch" />
      <el-select v-model="query.role" placeholder="全部角色" clearable>
        <el-option v-for="r in ROLE_OPTIONS" :key="r.value" :label="r.label" :value="r.value" />
      </el-select>
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button :icon="Refresh" @click="onReset">重置</el-button>
    </div>

    <div class="table-wrap">
      <el-table v-loading="loading" :data="rows" style="width: 100%">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" label="用户名" min-width="140" show-overflow-tooltip />
        <el-table-column prop="display_name" label="昵称" min-width="120" show-overflow-tooltip />
        <el-table-column prop="phone" label="手机号" min-width="130">
          <template #default="{ row }">{{ row.phone || '—' }}</template>
        </el-table-column>
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="ROLE_TAG[row.role] || 'info'" effect="plain">{{ ROLE_LABEL[row.role] || row.role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="偏好语言" width="110">
          <template #default="{ row }">{{ LANG_LABEL[row.lang_pref] || row.lang_pref }}</template>
        </el-table-column>
        <el-table-column prop="region" label="地区" min-width="110">
          <template #default="{ row }">{{ row.region || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'" effect="plain">
              {{ row.status === 'active' ? '正常' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近登录" min-width="170">
          <template #default="{ row }">{{ formatTime(row.last_login_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无用户" :image-size="90" />
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
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="isEdit" autocomplete="off" placeholder="登录用户名" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            autocomplete="new-password"
            show-password
            :placeholder="isEdit ? '留空表示不修改密码' : '请输入初始密码'"
          />
        </el-form-item>
        <el-form-item label="昵称" prop="display_name">
          <el-input v-model="form.display_name" autocomplete="off" placeholder="显示名称" />
        </el-form-item>
        <el-form-item label="手机号" prop="phone">
          <el-input v-model="form.phone" autocomplete="off" placeholder="选填" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="form.role" style="width: 100%">
            <el-option v-for="r in ROLE_OPTIONS" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="偏好语言" prop="lang_pref">
          <el-select v-model="form.lang_pref" style="width: 100%">
            <el-option v-for="l in LANG_OPTIONS" :key="l.value" :label="l.label" :value="l.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="地区" prop="region">
          <el-input v-model="form.region" autocomplete="off" placeholder="如：新疆喀什" />
        </el-form-item>
        <el-form-item label="状态" prop="status">
          <el-radio-group v-model="form.status">
            <el-radio value="active">正常</el-radio>
            <el-radio value="disabled">停用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
