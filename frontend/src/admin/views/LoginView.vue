<script setup>
/**
 * 登录页。演示账号直接写在页面上——这是内网演示系统，
 * 方便农技员第一次拿到系统就能进；正式环境应在后端移除默认密码。
 */
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useUserStore } from '@admin/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const formRef = ref(null)
const loading = ref(false)

const form = reactive({
  username: '',
  password: '',
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit() {
  if (!formRef.value) return
  // 表单校验不通过时不发请求，避免无意义的 422
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await userStore.login(form.username, form.password)
    ElMessage.success('登录成功')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
    router.replace(redirect)
  } catch (error) {
    // 登录失败提示由页面负责（拦截器刻意跳过 login 接口）
    ElMessage.error(error.response?.data?.message || '登录失败，请检查账号与网络')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  // 已登录直接放行（守卫也会拦，这里再兜一次体验更顺）
  if (userStore.token) router.replace('/dashboard')
})
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <span class="login-mark">农</span>
        <div>
          <h1 class="login-title">智慧农业多语言一体机</h1>
          <p class="login-sub">管理后台 · 农技员 / 管理员入口</p>
        </div>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" size="large" @submit.prevent="onSubmit">
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            autocomplete="username"
            :prefix-icon="User"
            clearable
          />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            autocomplete="current-password"
            :prefix-icon="Lock"
            show-password
            @keyup.enter="onSubmit"
          />
        </el-form-item>

        <el-button type="primary" class="login-btn" :loading="loading" @click="onSubmit">登 录</el-button>
      </el-form>

      <el-alert class="login-hint" type="success" :closable="false" show-icon>
        <template #title>
          演示账号：<b>admin</b> / <b>admin123</b>（首次启动后端自动创建）
        </template>
      </el-alert>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: radial-gradient(circle at 20% 20%, #1b3a2a 0%, #0e1a14 60%, #0b120f 100%);
}

.login-card {
  width: 400px;
  padding: 32px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.28);
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}

.login-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--admin-primary);
  color: #fff;
  font-size: 20px;
  font-weight: 700;
  flex: none;
}

.login-title {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
}

.login-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--admin-text-weak);
}

.login-btn {
  width: 100%;
  margin-top: 4px;
  letter-spacing: 4px;
}

.login-hint {
  margin-top: 18px;
  font-size: 12px;
}
</style>
