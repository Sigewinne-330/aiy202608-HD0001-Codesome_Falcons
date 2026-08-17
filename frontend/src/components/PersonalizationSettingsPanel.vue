<template>
  <section aria-labelledby="personalization-settings-title">
    <div class="panel-heading">
      <div>
        <h2 id="personalization-settings-title">{{ $t('personalization.settingsTitle') }}</h2>
        <p>{{ $t('personalization.settingsSubtitle') }}</p>
      </div>
      <v-chip :color="servingColor" variant="tonal" size="small">{{ servingLabel }}</v-chip>
    </div>

    <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-4">
      {{ error }}
      <button type="button" class="inline-action" @click="load">{{ $t('common.retry') }}</button>
    </v-alert>
    <v-alert v-if="saved" type="success" variant="tonal" density="compact" class="mb-4">
      {{ $t('personalization.saved') }}
    </v-alert>
    <v-skeleton-loader v-if="loading" type="list-item-three-line@4" />

    <template v-else>
      <div class="setting-row setting-row--primary">
        <div>
          <strong>{{ $t('personalization.enableTitle') }}</strong>
          <p>{{ $t('personalization.enableDesc') }}</p>
        </div>
        <v-switch
          v-model="form.operational_personalization_enabled"
          color="primary"
          hide-details
          :aria-label="$t('personalization.enableTitle')"
        />
      </div>
      <div v-for="control in controls" :key="control.key" class="setting-row">
        <div><strong>{{ control.title }}</strong><p>{{ control.description }}</p></div>
        <v-switch
          v-model="form[control.key]"
          :disabled="!form.operational_personalization_enabled"
          color="primary"
          hide-details
          :aria-label="control.title"
        />
      </div>
      <div class="setting-row setting-row--retention">
        <div>
          <strong>{{ $t('personalization.retentionTitle') }}</strong>
          <p>{{ $t('personalization.retentionDesc') }}</p>
        </div>
        <v-select
          v-model="form.raw_event_retention_days"
          :items="retentionOptions"
          item-title="title"
          item-value="value"
          density="compact"
          variant="outlined"
          hide-details
          class="retention-select"
          :aria-label="$t('personalization.retentionTitle')"
        />
      </div>
      <div class="privacy-state" aria-live="polite">
        <span><v-icon icon="mdi-shield-check-outline" size="18" />{{ $t('personalization.deterministicAlways') }}</span>
        <span>{{ $t('personalization.settingsVersion', { version: form.version || '—' }) }}</span>
        <span>{{ $t('personalization.policyVersion', { version: form.policy_version }) }}</span>
      </div>
      <div class="actions">
        <span v-if="dirty" class="dirty-copy">{{ $t('personalization.unsaved') }}</span>
        <v-spacer />
        <v-btn variant="outlined" :disabled="saving || !dirty" @click="load">{{ $t('personalization.undo') }}</v-btn>
        <v-btn color="primary" :loading="saving" :disabled="!dirty" @click="save">
          {{ $t('personalization.savePrivacy') }}
        </v-btn>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { personalizationApi } from '@/services/personalization'

const { t } = useI18n()
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const saved = ref(false)
const baseline = ref('')
const form = reactive({
  operational_personalization_enabled: false,
  work_session_capture_enabled: false,
  llm_memory_enabled: false,
  cross_user_learning_enabled: false,
  near_tie_exploration_enabled: false,
  raw_event_retention_days: 365,
  rebuild_after_reset_enabled: false,
  version: null,
  policy_version: 'scheduling-personalization-consent.v1',
  runtime: {},
  effective: {},
})

const controls = computed(() => [
  { key: 'work_session_capture_enabled', title: t('personalization.workSessionTitle'), description: t('personalization.workSessionDesc') },
  { key: 'llm_memory_enabled', title: t('personalization.memoryTitle'), description: t('personalization.memoryDesc') },
  { key: 'cross_user_learning_enabled', title: t('personalization.aggregateTitle'), description: t('personalization.aggregateDesc') },
  { key: 'near_tie_exploration_enabled', title: t('personalization.explorationTitle'), description: t('personalization.explorationDesc') },
])
const retentionOptions = computed(() => [
  { title: t('personalization.retention90'), value: 90 },
  { title: t('personalization.retention180'), value: 180 },
  { title: t('personalization.retention365'), value: 365 },
  { title: t('personalization.retention730'), value: 730 },
])
const comparable = () => JSON.stringify({
  operational_personalization_enabled: form.operational_personalization_enabled,
  work_session_capture_enabled: form.work_session_capture_enabled,
  llm_memory_enabled: form.llm_memory_enabled,
  cross_user_learning_enabled: form.cross_user_learning_enabled,
  near_tie_exploration_enabled: form.near_tie_exploration_enabled,
  raw_event_retention_days: form.raw_event_retention_days,
  rebuild_after_reset_enabled: form.rebuild_after_reset_enabled,
})
const dirty = computed(() => !loading.value && comparable() !== baseline.value)
const servingLabel = computed(() => t(`personalization.mode.${form.runtime?.serving_mode || 'unknown'}`))
const servingColor = computed(() => ({ suggestion: 'success', shadow: 'info', killed: 'warning', disabled: 'grey' }[form.runtime?.serving_mode] || 'grey'))

watch(() => form.operational_personalization_enabled, (enabled) => {
  if (!enabled) {
    form.work_session_capture_enabled = false
    form.llm_memory_enabled = false
    form.cross_user_learning_enabled = false
    form.near_tie_exploration_enabled = false
  }
})

function apply(value) {
  Object.assign(form, value)
  baseline.value = comparable()
}

async function load() {
  loading.value = true
  error.value = ''
  saved.value = false
  try {
    apply(await personalizationApi.settings())
  } catch (err) {
    error.value = err?.message || t('personalization.loadSettingsFailed')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    apply(await personalizationApi.saveSettings(form))
    saved.value = true
  } catch (err) {
    error.value = err?.status === 409
      ? t('personalization.settingsConflict')
      : (err?.message || t('personalization.saveSettingsFailed'))
  } finally {
    saving.value = false
  }
}

defineExpose({ save, dirty })
onMounted(load)
</script>

<style scoped>
.panel-heading { display: flex; justify-content: space-between; gap: 18px; padding-bottom: 18px; border-bottom: 1px solid var(--ib-border); }
.panel-heading h2 { margin: 0; color: var(--ib-text); font-size: 21px; }
.panel-heading p, .setting-row p { margin: 5px 0 0; color: var(--ib-text-secondary); font-size: 12px; line-height: 1.55; }
.setting-row { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 17px 0; border-bottom: 1px solid var(--ib-border); }
.setting-row > div:first-child { max-width: 520px; }
.setting-row strong { color: var(--ib-text); }
.setting-row--primary { margin-top: 12px; }
.retention-select { max-width: 210px; }
.privacy-state { display: flex; flex-wrap: wrap; gap: 14px 24px; margin-top: 18px; padding: 12px 14px; border: 1px solid var(--ib-border); border-radius: var(--ib-radius-md); color: var(--ib-text-secondary); background: var(--ib-surface-subtle); font-size: 12px; }
.privacy-state span { display: inline-flex; align-items: center; gap: 5px; }
.actions { display: flex; align-items: center; gap: 10px; margin-top: 22px; }
.dirty-copy { color: var(--ib-warning); font-size: 12px; }
.inline-action { border: 0; color: inherit; text-decoration: underline; background: none; cursor: pointer; }
@media (max-width: 600px) {
  .panel-heading, .setting-row { align-items: flex-start; }
  .setting-row { gap: 10px; }
  .setting-row--retention { flex-direction: column; }
  .retention-select { width: 100%; max-width: none; }
  .actions { flex-wrap: wrap; }
}
</style>
