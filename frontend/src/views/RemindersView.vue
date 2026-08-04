<template>
  <section class="reminders-page">
    <header class="page-header">
      <div>
        <div class="eyebrow">REMINDER CENTER</div>
        <h1>{{ $t('reminders.title') }}</h1>
        <p>{{ $t('reminders.subtitle') }}</p>
      </div>
    </header>

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
import { useAuth } from '@/stores/auth'
import ReminderHistoryList from '@/components/ReminderHistoryList.vue'
import ReminderSettingsPanel from '@/components/ReminderSettingsPanel.vue'

const VALID_TABS = ['history', 'settings']

const route = useRoute()
const router = useRouter()
const { logout } = useAuth()

const historyList = ref(null)

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
</style>
