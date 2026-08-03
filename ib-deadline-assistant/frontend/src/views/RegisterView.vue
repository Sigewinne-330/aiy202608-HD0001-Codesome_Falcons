<template>
  <v-container class="fill-height d-flex align-center justify-center">
    <v-card class="pa-6" max-width="420" width="100%" elevation="4" rounded="xl">
      <div class="text-center mb-6">
        <router-link
          to="/"
          class="text-body-2 text-decoration-none text-grey d-inline-flex align-center mb-3"
        >
          <v-icon size="16" class="mr-1">mdi-arrow-left</v-icon>
          {{ $t('auth.backToLanding') }}
        </router-link>
        <v-icon size="48" color="primary" class="mb-2">mdi-account-plus-outline</v-icon>
        <h2 class="text-h5 font-weight-bold">{{ $t('auth.registerTitle') }}</h2>
        <p class="text-body-2 text-grey mt-1">{{ $t('auth.registerSubtitle') }}</p>
      </div>

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

      <v-alert v-if="successMsg" type="success" variant="tonal" class="mb-4">
        {{ successMsg }}
      </v-alert>

      <v-form
        v-if="step === 'details'"
        ref="detailsFormRef"
        v-model="detailsValid"
        @submit.prevent="handleSendCode"
      >
        <v-text-field
          v-model="username"
          :label="$t('auth.username')"
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
          :label="$t('auth.emailRequired')"
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
          :label="$t('auth.password')"
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
          :label="$t('auth.confirmPassword')"
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
          :loading="sendingCode"
          rounded="lg"
          class="mb-4"
        >
          {{ $t('auth.sendVerificationCode') }}
        </v-btn>
      </v-form>

      <v-form
        v-else
        ref="codeFormRef"
        v-model="codeValid"
        @submit.prevent="handleVerifyAndRegister"
      >
        <div class="d-flex align-center justify-space-between mb-3">
          <div>
            <div class="text-caption text-medium-emphasis">{{ $t('auth.codeSentTo') }}</div>
            <div class="text-body-2 font-weight-medium">{{ verificationEmail }}</div>
          </div>
          <v-btn variant="text" size="small" color="primary" @click="resetEmail">
            {{ $t('auth.changeEmail') }}
          </v-btn>
        </div>

        <v-text-field
          v-model="verificationCode"
          :label="$t('auth.verificationCode')"
          prepend-inner-icon="mdi-shield-key-outline"
          :rules="codeRules"
          variant="outlined"
          density="comfortable"
          class="mb-3"
          autocomplete="one-time-code"
          inputmode="numeric"
          maxlength="6"
        />

        <v-btn
          type="submit"
          color="primary"
          size="large"
          block
          :loading="registering"
          rounded="lg"
          class="mb-2"
        >
          {{ $t('auth.verifyAndRegister') }}
        </v-btn>

        <v-btn
          variant="text"
          color="primary"
          block
          :disabled="resendSeconds > 0"
          :loading="sendingCode"
          class="mb-4"
          @click="handleResend"
        >
          {{ resendSeconds > 0
            ? $t('auth.resendCountdown', { seconds: resendSeconds })
            : $t('auth.resendCode') }}
        </v-btn>
      </v-form>

      <div class="text-center">
        <span class="text-body-2 text-grey">{{ $t('auth.haveAccount') }}</span>
        <router-link to="/login" class="text-body-2 text-decoration-none font-weight-bold ml-1">
          {{ $t('auth.loginNow') }}
        </router-link>
      </div>
    </v-card>
  </v-container>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { API_ERROR_KIND, useAuth } from '@/stores/auth'
import { useI18n } from 'vue-i18n'

const router = useRouter()
const { t } = useI18n()
const { requestVerificationCode, verifyEmailCode, register, login } = useAuth()

const step = ref('details')
const detailsValid = ref(false)
const codeValid = ref(false)
const detailsFormRef = ref(null)
const codeFormRef = ref(null)
const username = ref('')
const email = ref('')
const verificationEmail = ref('')
const verificationCode = ref('')
const verificationToken = ref('')
const password = ref('')
const confirmPassword = ref('')
const showPwd = ref(false)
const showConfirmPwd = ref(false)
const errorMsg = ref('')
const successMsg = ref('')
const sendingCode = ref(false)
const registering = ref(false)
const resendSeconds = ref(0)
let resendTimer = null

const usernameRules = [
  (v) => !!v || t('auth.usernameRequired'),
  (v) => (v && v.trim().length >= 2) || t('auth.usernameMin'),
  (v) => (v && v.trim().length <= 50) || t('auth.usernameMax'),
]

const emailRules = [
  (v) => !!v || t('auth.emailRequired'),
  (v) => /.+@.+\..+/.test(v || '') || t('auth.emailInvalid'),
]

const passwordRules = [
  (v) => !!v || t('auth.passwordRequired'),
  (v) => (v && v.length >= 6) || t('auth.passwordMin'),
]

const confirmPasswordRules = [
  (v) => !!v || t('auth.confirmRequired'),
  (v) => v === password.value || t('auth.confirmMismatch'),
]

const codeRules = [
  (v) => !!v || t('auth.verificationCodeRequired'),
  (v) => /^\d{6}$/.test(v || '') || t('auth.verificationCodeInvalid'),
]

function normalizedEmail() {
  return email.value.trim().toLowerCase()
}

function clearCountdown() {
  if (resendTimer) window.clearInterval(resendTimer)
  resendTimer = null
}

function startCountdown(seconds) {
  clearCountdown()
  resendSeconds.value = Math.max(0, Number(seconds) || 60)
  resendTimer = window.setInterval(() => {
    resendSeconds.value -= 1
    if (resendSeconds.value <= 0) clearCountdown()
  }, 1000)
}

function resetVerificationState() {
  clearCountdown()
  step.value = 'details'
  verificationEmail.value = ''
  verificationCode.value = ''
  verificationToken.value = ''
  resendSeconds.value = 0
  successMsg.value = ''
}

function resetEmail() {
  errorMsg.value = ''
  resetVerificationState()
}

function registrationErrorMessage(error) {
  if (error?.kind === API_ERROR_KIND.TRANSPORT) {
    return t('auth.serverUnavailable')
  }
  if (error?.status === 503) {
    return t('auth.emailServiceUnavailable')
  }
  return error?.message || t('auth.requestFailed')
}

async function sendCode() {
  sendingCode.value = true
  errorMsg.value = ''
  successMsg.value = ''
  try {
    const targetEmail = normalizedEmail()
    const data = await requestVerificationCode(targetEmail)
    verificationToken.value = ''
    verificationEmail.value = targetEmail
    step.value = 'code'
    successMsg.value = data.message
    startCountdown(data.retry_after_seconds)
  } catch (error) {
    errorMsg.value = registrationErrorMessage(error)
  } finally {
    sendingCode.value = false
  }
}

async function handleSendCode() {
  const { valid } = await detailsFormRef.value.validate()
  if (!valid) return
  await sendCode()
}

async function handleResend() {
  if (resendSeconds.value > 0 || sendingCode.value) return
  verificationCode.value = ''
  await sendCode()
}

async function handleVerifyAndRegister() {
  const { valid } = await codeFormRef.value.validate()
  if (!valid) return

  registering.value = true
  errorMsg.value = ''
  successMsg.value = ''

  try {
    if (!verificationToken.value) {
      const proof = await verifyEmailCode(
        verificationEmail.value,
        verificationCode.value,
      )
      verificationToken.value = proof.verification_token
    }
    await register(
      username.value.trim(),
      verificationEmail.value,
      password.value,
      verificationToken.value,
    )
    router.push('/calendar')
  } catch (error) {
    // 网络抖动可能发生在后端已写入用户之后；用登录确认，避免重复注册。
    if (verificationToken.value) {
      try {
        await login(verificationEmail.value, password.value)
        router.push('/calendar')
        return
      } catch {
        // 注册未完成时保留原始错误。
      }
    }
    errorMsg.value = registrationErrorMessage(error)
  } finally {
    registering.value = false
  }
}

watch(email, () => {
  if (step.value === 'code' && normalizedEmail() !== verificationEmail.value) {
    resetVerificationState()
  }
})

onBeforeUnmount(clearCountdown)
</script>
