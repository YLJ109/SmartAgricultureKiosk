<script setup>
/**
 * 操作日志：谁在什么时候改了什么。只读，不提供删除。
 * action 选项来自后端 admin.py / auth.py 实际写入的动作名。
 */
import { onMounted, reactive, ref } from 'vue'
import { Search, Refresh } from '@element-plus/icons-vue'
import { logApi } from '@admin/api'

const ACTION_OPTIONS = [
  { value: 'create_user', label: '新建用户' },
  { value: 'update_user', label: '更新用户' },
  { value: 'delete_user', label: '删除用户' },
  { value: 'create_provider', label: '新增厂商' },
  { value: 'update_provider', label: '更新厂商' },
  { value: 'delete_provider', label: '删除厂商' },
  { value: 'test_provider', label: '测试厂商' },
  { value: 'create_lang_resource', label: '新增词条' },
  { value: 'update_lang_resource', label: '更新词条' },
  { value: 'delete_lang_resource', label: '删除词条' },
  { value: 'guest_login', label: '游客接入' },
]
const ACTION_LABEL = Object.fromEntries(ACTION_OPTIONS.map((a) => [a.value, a.label]))

// 危险动作标红，便于快速扫出破坏性操作
const DANGER_ACTIONS = new Set(['delete_user', 'delete_provider', 'delete_lang_resource'])

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const query = reactive({ page: 1, page_size: 20, action: '', keyword: '' })

async function load() {
  loading.value = true
  try {
    const res = await logApi.list({
      page: query.page,
      page_size: query.page_size,
      action: query.action || undefined,
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
  query.action = ''
  query.keyword = ''
  query.page = 1
  load()
}

function onPageChange(page) {
  query.page = page
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
        <h2 class="page-title">操作日志</h2>
        <p class="page-sub">后台所有写操作的审计记录</p>
      </div>
    </div>

    <div class="filter-bar">
      <el-select v-model="query.action" placeholder="全部动作" clearable>
        <el-option v-for="a in ACTION_OPTIONS" :key="a.value" :label="a.label" :value="a.value" />
      </el-select>
      <el-input v-model="query.keyword" placeholder="操作人 / 对象 / 详情" clearable :prefix-icon="Search" @keyup.enter="onSearch" />
      <el-button type="primary" @click="onSearch">查询</el-button>
      <el-button :icon="Refresh" @click="onReset">重置</el-button>
    </div>

    <div class="table-wrap">
      <el-table v-loading="loading" :data="rows" style="width: 100%">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column label="时间" min-width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="actor" label="操作人" width="140" show-overflow-tooltip />
        <el-table-column label="动作" width="130">
          <template #default="{ row }">
            <el-tag size="small" :type="DANGER_ACTIONS.has(row.action) ? 'danger' : 'info'" effect="plain">
              {{ ACTION_LABEL[row.action] || row.action }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="target" label="对象" min-width="160" show-overflow-tooltip />
        <el-table-column prop="detail" label="详情" min-width="240" show-overflow-tooltip />
        <el-table-column prop="ip" label="IP" width="140" />
        <template #empty>
          <el-empty description="暂无操作日志" :image-size="90" />
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
  </div>
</template>
