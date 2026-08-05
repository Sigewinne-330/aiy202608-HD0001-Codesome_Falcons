<template>
  <section class="reminders-page">
    <header class="page-header">
      <div>
        <div class="eyebrow">REMINDER CENTER</div>
        <h1>{{ $t('reminders.title') }}</h1>
        <p>{{ $t('reminders.subtitle') }}</p>
      </div>
    </header>

    <v-card v-if="demoEnabled" class="demo-card" variant="tonal" color="primary">
      <v-card-title class="demo-card__title">
        <v-icon icon="mdi-bell-ring-outline" size="20" />
        {{ $t('reminders.demoTitle') }}
      </v-card-title>
      <v-card-text>
        <p class="demo-card__help">{{ $t('reminders.demoHelp') }}</p>
        <v-alert v-if="demoError" type="error" variant="tonal" density="comfortable" class="mb-3">
          {{ demoError }}
        </v-alert>
        <v-alert v-if="demoResult" type="success" variant="tonal" density="comfortable" class="mb-3">
          <div>{{ demoResult.message }}</div>
          <div class="demo-subject">{{ demoResult.subject }}</div>
          <div class="demo-outcomes">
            <span>{{ $t('reminders.demoChat') }}：{{ demoStatus(demoResult.chat.status) }}</span>
            <span>{{ $t('reminders.demoEmail') }}：{{ demoStatus(demoResult.email.status) }}</span>
          </div>
        </v-alert>
        <v-btn
          color="primary"
          prepend-icon="mdi-send-check-outline"
          :loading="demoSending"
          :disabled="demoSending"
          @click="sendDemo"
        >
          {{ $t('reminders.demoButton') }}
        </v-btn>
      </v-card-text>
    </v-card>

    <v-tabs
      :model-value="activeTab"
      color="primary"
      class="reminders-tabs"
      @update:model-value="switchTab"
    >
      <v-tab value="history" prepend-icon="mdi-history">{{ $t('reminders.tabHistory') }}</v-tab>
      <v-tab value="settings" prepend-icon="mdi-tune-variant">{{ $t('reminders.tabSettings') }}</v-tab>
    </v-tabs>

    <div class="reminders-body">
      <ReminderHistoryList
        v-show="activeTab === 'history'"
        ref="historyList"
        :digest-anchor="digestAnchor"
        @unauthorized="handleUnauthorized"
      />
      <ReminderSettingsPanel
        v-show="activeTab === 'settings'"
        @unauthorized="handleUnauthorized"
      />
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuth } from '@/stores/auth'
import ReminderHistoryList from '@/components/ReminderHistoryList.vue'
import ReminderSettingsPanel from '@/components/ReminderSettingsPanel.vue'
import { ApiError, sendDemoReminder } from '@/services/reminders'

const VALID_TABS = ['history', 'settings']

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { logout } = useAuth()

const historyList = ref(null)
const demoEnabled = import.meta.env.VITE_DEMO_REMINDER_ENABLED === 'true'
const demoSending = ref(false)
const demoResult = ref(null)
const demoError = ref('')

const activeTab = computed(() => (VALID_TABS.includes(route.query.tab) ? route.query.tab : 'history'))
const digestAnchor = computed(() => {
  const raw = route.query.digest
  const n = Number(raw)
  return raw != null && Number.isFinite(n) ? n : null
})

function switchTab(tab) {
  if (!VALID_TABS.includes(tab) || tab === activeTab.value) return
  const query = { ...route.query, tab }
  if (tab !== 'history') delete query.digest
  router.replace({ path: '/reminders', query })
}

function demoStatus(status) {
  const labels = {
    delivered: 'reminders.demoDelivered',
    skipped: 'reminders.demoSkipped',
    failed: 'reminders.demoFailed',
    retryable: 'reminders.demoRetryable',
  }
  return labels[status] ? t(labels[status]) : status
}

async function sendDemo() {
  if (demoSending.value) return
  demoSending.value = true
  demoError.value = ''
  demoResult.value = null
  try {
    demoResult.value = await sendDemoReminder()
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      handleUnauthorized()
      return
    }
    demoError.value = error?.message || t('reminders.demoFailed')
  } finally {
    demoSending.value = false
  }
}

// 非法 tab 自动替换为 history
watch(
  () => route.query.tab,
  (tab) => {
    if (tab != null && !VALID_TABS.includes(tab)) {
      router.replace({ path: '/reminders', query: { ...route.query, tab: 'history' } })
    }
  },
  { immediate: true },
)

// 提醒中心范围内的 401：登出并跳登录，保留回跳地址
function handleUnauthorized() {
  logout()
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}
</script>

<style scoped>
.reminders-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 28px 24px 60px;
}
.page-header h1 {
  font-size: 26px;
  color: #202633;
  margin: 4px 0 6px;
}
.page-header p {
  color: #858d9d;
  font-size: 13px;
}
.eyebrow {
  font-size: 11px;
  letter-spacing: 0.14em;
  color: #6c7a96;
  font-weight: 600;
}
.reminders-tabs {
  margin-top: 20px;
  border-bottom: 1px solid #e8ebf0;
}
.reminders-body {
  padding-top: 22px;
}
.demo-card {
  margin-top: 20px;
}
.demo-card__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
}
.demo-card__help {
  margin: 0 0 14px;
  font-size: 13px;
}
.demo-subject {
  margin-top: 6px;
  font-weight: 600;
}
.demo-outcomes {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 12px;
}
</style>
