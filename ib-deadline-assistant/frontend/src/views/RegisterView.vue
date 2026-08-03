<template>
  <v-container class="fill-height d-flex align-center justify-center">
    <v-card class="pa-6" max-width="420" width="100%" elevation="4" rounded="xl">
      <!-- 标题 -->
      <div class="text-center mb-6">
        <v-icon size="48" color="primary" class="mb-2">mdi-account-plus-outline</v-icon>
        <h2 class="text-h5 font-weight-bold">创建账号</h2>
        <p class="text-body-2 text-grey mt-1">加入任务规划师，高效管理你的任务</p>
      </div>

      <!-- 错误提示 -->
      <v-alert
        v-if="errorMsg"
        type="error"
        variant="tonal"
        closable
        class="mb-4"
        @click:close="errorMsg = ''"
      >
        {{ errorMsg }}
      </v-alert>

      <!-- 注册表单 -->
      <v-form ref="formRef" v-model="formValid" @submit.prevent="handleRegister">
        <v-text-field
          v-model="username"
          label="用户名"
          prepend-inner-icon="mdi-account-outline"
          :rules="usernameRules"
          variant="outlined"
          density="comfortable"
          class="mb-3"
          autocomplete="username"
          clearable
        />

        <v-text-field
          v-model="email"
          label="邮箱（选填）"
          type="email"
          prepend-inner-icon="mdi-email-outline"
          :rules="emailRules"
          variant="outlined"
          density="comfortable"
          class="mb-3"
          autocomplete="email"
          clearable
        />

        <v-text-field
          v-model="password"
          label="密码"
          :type="showPwd ? 'text' : 'password'"
          prepend-inner-icon="mdi-lock-outline"
          :append-inner-icon="showPwd ? 'mdi-eye-off' : 'mdi-eye'"
          @click:append-inner="showPwd = !showPwd"
          :rules="passwordRules"
          variant="outlined"
          density="comfortable"
          class="mb-3"
          autocomplete="new-password"
        />

        <v-text-field
          v-model="confirmPassword"
          label="确认密码"
          :type="showConfirmPwd ? 'text' : 'password'"
          prepend-inner-icon="mdi-lock-check-outline"
          :append-inner-icon="showConfirmPwd ? 'mdi-eye-off' : 'mdi-eye'"
          @click:append-inner="showConfirmPwd = !showConfirmPwd"
          :rules="confirmPasswordRules"
          variant="outlined"
          density="comfortable"
          class="mb-4"
          autocomplete="new-password"
        />

        <v-btn
          type="submit"
          color="primary"
          size="large"
          block
          :loading="loading"
          rounded="lg"
          class="mb-4"
        >
          注 册
        </v-btn>
      </v-form>

      <!-- 底部链接 -->
      <div class="text-center">
        <span class="text-body-2 text-grey">已有账号？</span>
        <router-link to="/login" class="text-body-2 text-decoration-none font-weight-bold ml-1">
          立即登录
        </router-link>
      </div>
    </v-card>
  </v-container>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'

const router = useRouter()
const { register } = useAuth()

const formValid = ref(false)
const formRef = ref(null)
const username = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const showPwd = ref(false)
const showConfirmPwd = ref(false)
const errorMsg = ref('')
const loading = ref(false)

const usernameRules = [
  (v) => !!v || '请输入用户名',
  (v) => (v && v.length >= 2) || '用户名至少 2 个字符',
  (v) => (v && v.length <= 50) || '用户名最多 50 个字符',
]

const emailRules = [
  (v) => !v || /.+@.+\..+/.test(v) || '请输入有效的邮箱地址',
]

const passwordRules = [
  (v) => !!v || '请输入密码',
  (v) => (v && v.length >= 6) || '密码至少 6 个字符',
]

const confirmPasswordRules = [
  (v) => !!v || '请确认密码',
  (v) => v === password.value || '两次输入的密码不一致',
]

async function handleRegister() {
  const { valid } = await formRef.value.validate()
  if (!valid) return

  loading.value = true
  errorMsg.value = ''

  try {
    await register(username.value, email.value, password.value)
    router.push('/calendar')
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    loading.value = false
  }
}
</script>
