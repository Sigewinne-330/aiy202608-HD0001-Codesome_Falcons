<template>
  <v-container class="fill-height d-flex align-center justify-center">
    <v-card class="pa-6" max-width="420" width="100%" elevation="4" rounded="xl">
      <!-- 标题 -->
      <div class="text-center mb-6">
        <router-link
          to="/"
          class="text-body-2 text-decoration-none text-grey d-inline-flex align-center mb-3"
        >
          <v-icon size="16" class="mr-1">mdi-arrow-left</v-icon>
          {{ $t('auth.backToLanding') }}
        </router-link>
        <v-icon size="48" color="primary" class="mb-2">mdi-calendar-edit</v-icon>
        <h2 class="text-h5 font-weight-bold">{{ $t('auth.loginTitle') }}</h2>
        <p class="text-body-2 text-grey mt-1">{{ $t('auth.loginSubtitle') }}</p>
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

      <!-- 登录表单 -->
      <v-form ref="formRef" v-model="formValid" @submit.prevent="handleLogin">
        <v-text-field
          v-model="email"
          :label="$t('auth.usernameOrEmail')"
          prepend-inner-icon="mdi-account-outline"
          :rules="accountRules"
          variant="outlined"
          density="comfortable"
          class="mb-3"
          autocomplete="username"
          clearable
        />

        <v-text-field
          v-model="password"
          :label="$t('auth.password')"
          :type="showPwd ? 'text' : 'password'"
          prepend-inner-icon="mdi-lock-outline"
          :append-inner-icon="showPwd ? 'mdi-eye-off' : 'mdi-eye'"
          @click:append-inner="showPwd = !showPwd"
          :rules="passwordRules"
          variant="outlined"
          density="comfortable"
          class="mb-4"
          autocomplete="current-password"
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
          {{ $t('auth.loginBtn') }}
        </v-btn>
      </v-form>

      <!-- 底部链接 -->
      <div class="text-center">
        <span class="text-body-2 text-grey">{{ $t('auth.noAccount') }}</span>
        <router-link to="/register" class="text-body-2 text-decoration-none font-weight-bold ml-1">
          {{ $t('auth.registerNow') }}
        </router-link>
      </div>
    </v-card>
  </v-container>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuth } from '@/stores/auth'

const router = useRouter()
const { t } = useI18n()
const { login } = useAuth()

const formValid = ref(false)
const formRef = ref(null)
const email = ref('')
const password = ref('')
const showPwd = ref(false)
const errorMsg = ref('')
const loading = ref(false)

const accountRules = [
  (v) => !!v || t('auth.accountRequired'),
]

const passwordRules = [
  (v) => !!v || t('auth.passwordRequired'),
]

async function handleLogin() {
  const { valid } = await formRef.value.validate()
  if (!valid) return

  loading.value = true
  errorMsg.value = ''

  try {
    await login(email.value, password.value)
    router.push('/calendar')
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    loading.value = false
  }
}
</script>
