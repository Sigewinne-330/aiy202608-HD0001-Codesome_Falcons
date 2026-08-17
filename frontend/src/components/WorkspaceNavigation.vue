<template>
  <v-navigation-drawer
    v-model="model"
    class="workspace-navigation"
    :permanent="mdAndUp"
    :temporary="!mdAndUp"
    :rail="mdAndUp && rail"
    :rail-width="72"
    :width="244"
    :scrim="true"
  >
    <div class="nav-brand" role="button" tabindex="0" @click="goHome" @keydown.enter="goHome">
      <span class="nav-brand__mark">IB</span>
      <span v-if="!rail || !mdAndUp" class="nav-brand__copy">
        <strong>IBuddy</strong>
        <small>{{ $t('landing.slogan') }}</small>
      </span>
    </div>

    <v-list class="nav-list" nav density="comfortable" :aria-label="$t('app.navigation')">
      <v-list-item
        v-for="item in primaryItems"
        :key="item.to"
        :to="item.to"
        :prepend-icon="item.icon"
        :title="$t(item.label)"
        :active="isActive(item)"
        rounded="lg"
      />
    </v-list>

    <template #append>
      <div class="nav-utilities">
        <v-list nav density="comfortable">
          <v-list-item
            prepend-icon="mdi-creation-outline"
            :title="$t('app.agent')"
            rounded="lg"
            @click="$emit('open-agent')"
          />
          <v-list-item
            to="/billing"
            prepend-icon="mdi-wallet-outline"
            :title="$t('billing.title')"
            rounded="lg"
          />
          <v-list-item
            :prepend-icon="themeIcon"
            :title="themeLabel"
            rounded="lg"
            @click="cycleThemeMode"
          />
          <v-list-item
            prepend-icon="mdi-cog-outline"
            :title="$t('app.settings')"
            rounded="lg"
            @click="$emit('open-settings')"
          />
        </v-list>
        <v-btn
          v-if="mdAndUp"
          class="nav-collapse"
          :icon="rail ? 'mdi-chevron-right' : 'mdi-chevron-left'"
          variant="text"
          size="small"
          :aria-label="rail ? $t('app.expandNavigation') : $t('app.collapseNavigation')"
          @click="rail = !rail"
        />
      </div>
    </template>
  </v-navigation-drawer>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDisplay } from 'vuetify'
import { useI18n } from 'vue-i18n'
import { useAppTheme } from '@/services/theme'

defineEmits(['open-agent', 'open-settings'])
const model = defineModel({ type: Boolean, default: true })

const route = useRoute()
const router = useRouter()
const { mdAndUp } = useDisplay()
const { t } = useI18n()
const { mode, cycleThemeMode } = useAppTheme()
const rail = ref(true)

const primaryItems = [
  { to: '/calendar', icon: 'mdi-calendar-blank-outline', label: 'nav.calendar' },
  { to: '/tasks', icon: 'mdi-check-circle-outline', label: 'nav.tasks' },
  { to: '/deadlines', icon: 'mdi-calendar-alert-outline', label: 'nav.deadlines' },
  { to: '/urgent', icon: 'mdi-lightning-bolt-outline', label: 'nav.urgent' },
  { to: '/progress', icon: 'mdi-chart-timeline-variant', label: 'nav.progress' },
  { to: '/reminders', icon: 'mdi-bell-outline', label: 'reminders.title' },
]

const themeIcon = computed(() => ({
  system: 'mdi-theme-light-dark',
  light: 'mdi-white-balance-sunny',
  dark: 'mdi-weather-night',
})[mode.value])
const themeLabel = computed(() => t(`app.theme${mode.value[0].toUpperCase()}${mode.value.slice(1)}`))

function isActive(item) {
  return item.to === '/progress' ? route.path.startsWith('/progress') : route.path === item.to
}

function goHome() {
  router.push('/calendar')
}
</script>

<style scoped>
.workspace-navigation {
  border-right: 1px solid var(--ib-border) !important;
  background: color-mix(in srgb, var(--ib-surface) 96%, transparent) !important;
}

.nav-brand {
  display: flex;
  min-height: 64px;
  align-items: center;
  gap: 11px;
  padding: 10px 16px;
  cursor: pointer;
}

.nav-brand__mark {
  display: grid;
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  place-items: center;
  border-radius: 12px;
  background: var(--ib-primary);
  color: var(--ib-on-primary);
  font-size: 13px;
  font-weight: 800;
  letter-spacing: .04em;
}

.nav-brand__copy { display: grid; min-width: 0; line-height: 1.15; }
.nav-brand__copy strong { color: var(--ib-text); font-size: 16px; }
.nav-brand__copy small { margin-top: 4px; color: var(--ib-text-muted); font-size: 10px; white-space: nowrap; }
.nav-list { padding: 10px; }
.nav-list :deep(.v-list-item),
.nav-utilities :deep(.v-list-item) { margin-bottom: 4px; color: var(--ib-text-secondary); }
.nav-list :deep(.v-list-item--active) { background: var(--ib-primary-soft); color: var(--ib-primary-strong); }
.nav-utilities { border-top: 1px solid var(--ib-border); padding: 8px 10px 10px; }
.nav-collapse { display: block; margin: 2px auto 0; color: var(--ib-text-muted); }
</style>
