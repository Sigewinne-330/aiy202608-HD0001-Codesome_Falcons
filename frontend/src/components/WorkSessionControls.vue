<template>
  <section class="work-controls" aria-labelledby="work-controls-title">
    <div class="work-controls__title">
      <div>
        <strong id="work-controls-title">{{ $t('personalization.focusRecordTitle') }}</strong>
        <span>{{ $t('personalization.focusRecordSubtitle') }}</span>
      </div>
      <v-chip size="x-small" :color="stateColor" variant="tonal">{{ stateLabel }}</v-chip>
    </div>
    <v-alert v-if="captureDisabled" type="info" density="compact" variant="tonal">
      {{ $t('personalization.focusCaptureDisabled') }}
    </v-alert>
    <template v-else>
      <v-select
        v-model="selectedKey"
        :items="taskOptions"
        item-title="title"
        item-value="key"
        :label="$t('personalization.selectTask')"
        density="compact"
        variant="outlined"
        hide-details
        :disabled="Boolean(session)"
      />
      <div class="timer" aria-live="polite">
        <strong>{{ elapsedLabel }}</strong>
        <span v-if="selectedTask">{{ selectedTask.title }}</span>
      </div>
      <div class="work-actions">
        <v-btn v-if="!session" size="small" color="primary" prepend-icon="mdi-play" :disabled="!selectedTask" :loading="busy" @click="start">
          {{ $t('personalization.start') }}
        </v-btn>
        <v-btn v-else-if="session.state === 'active'" size="small" variant="tonal" prepend-icon="mdi-pause" :loading="busy" @click="transition('pause')">
          {{ $t('personalization.pause') }}
        </v-btn>
        <v-btn v-else size="small" variant="tonal" prepend-icon="mdi-play" :loading="busy" @click="transition('resume')">
          {{ $t('personalization.resume') }}
        </v-btn>
        <v-btn v-if="session" size="small" color="primary" variant="outlined" prepend-icon="mdi-stop" :loading="busy" @click="transition('stop')">
          {{ $t('personalization.stop') }}
        </v-btn>
        <v-btn v-if="selectedTask" size="small" variant="text" @click="outcomeOpen = true">
          {{ $t('personalization.recordOutcome') }}
        </v-btn>
      </div>
    </template>
    <v-alert v-if="error" type="error" density="compact" variant="tonal" class="mt-2">
      {{ error }}
      <template #append><v-btn size="x-small" variant="text" @click="load">{{ $t('common.retry') }}</v-btn></template>
    </v-alert>

    <v-dialog v-model="outcomeOpen" max-width="470">
      <v-card>
        <v-card-title>{{ $t('personalization.outcomeDialogTitle') }}</v-card-title>
        <v-card-text>
          <v-select v-model="outcome.terminal_state" :items="outcomeOptions" :label="$t('personalization.outcome')" />
          <div class="progress-field">
            <span>{{ $t('personalization.completionProgress') }}</span>
            <strong>{{ outcome.progress }}%</strong>
          </div>
          <v-slider v-model="outcome.progress" :aria-label="$t('personalization.completionProgress')" :min="0" :max="100" step="5" thumb-label />
          <v-text-field v-model.number="outcome.minutes" type="number" min="0" max="100000" :label="$t('personalization.actualMinutesOptional')" />
          <v-textarea
            v-if="outcome.terminal_state === 'reasonably_abandoned'"
            v-model="outcome.reason"
            :label="$t('personalization.abandonReasonOptional')"
            counter="64"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="outcomeOpen = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="primary" :loading="busy" @click="submitOutcome">{{ $t('common.save') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { notify } from '@/services/feedback'
import { parseServerTimestamp, personalizationApi } from '@/services/personalization'

const props = defineProps({ tasks: { type: Array, default: () => [] } })
const { t } = useI18n()
const settings = ref(null)
const session = ref(null)
const selectedKey = ref('')
const busy = ref(false)
const error = ref('')
const tick = ref(Date.now())
const outcomeOpen = ref(false)
const outcome = reactive({ terminal_state: 'completed', progress: 100, minutes: null, reason: '' })
const outcomeOptions = computed(() => ['completed', 'reasonably_abandoned', 'confirmed_miss', 'unknown']
  .map((value) => ({ title: t(`personalization.outcomeState.${value}`), value })))
const taskOptions = computed(() => props.tasks.map((item) => ({ ...item, key: `${item.source_type}:${item.id}` })))
const selectedTask = computed(() => taskOptions.value.find((item) => item.key === selectedKey.value) || null)
const captureDisabled = computed(() => settings.value != null && !settings.value?.effective?.work_session_capture)
const stateLabel = computed(() => t(`personalization.sessionState.${captureDisabled.value ? 'disabled' : (session.value?.state || 'idle')}`))
const stateColor = computed(() => captureDisabled.value ? 'grey' : session.value?.state === 'paused' ? 'warning' : session.value ? 'success' : 'primary')
const elapsedSeconds = computed(() => {
  if (!session.value) return 0
  const base = Number(session.value.accumulated_active_seconds || 0)
  if (session.value.state !== 'active') return base
  const startedAt = parseServerTimestamp(session.value.started_at)
  return base + (Number.isFinite(startedAt) ? Math.max(0, Math.floor((tick.value - startedAt) / 1000)) : 0)
})
const elapsedLabel = computed(() => {
  const seconds = elapsedSeconds.value
  return `${String(Math.floor(seconds / 3600)).padStart(2, '0')}:${String(Math.floor((seconds % 3600) / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
})

async function load() {
  error.value = ''
  try {
    const [settingResult, active] = await Promise.all([personalizationApi.settings(), personalizationApi.activeSessions()])
    settings.value = settingResult
    session.value = active.items[0] || null
    if (session.value) selectedKey.value = `${session.value.source.source_type}:${session.value.source.source_id}`
    else if (!selectedKey.value && taskOptions.value.length) selectedKey.value = taskOptions.value[0].key
  } catch (err) {
    error.value = err?.message || t('personalization.loadFocusFailed')
  }
}

async function start() {
  if (!selectedTask.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await personalizationApi.startSession({ source_type: selectedTask.value.source_type, source_id: selectedTask.value.id })
    session.value = result.session
  } catch (err) {
    error.value = err?.message || t('personalization.startFailed')
  } finally {
    busy.value = false
  }
}

async function transition(action) {
  if (!session.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await personalizationApi.transitionSession(session.value.id, action)
    session.value = result.session?.state === 'stopped' ? null : result.session
  } catch (err) {
    error.value = err?.message || t('personalization.sessionActionFailed')
  } finally {
    busy.value = false
  }
}

async function submitOutcome() {
  if (!selectedTask.value) return
  busy.value = true
  error.value = ''
  try {
    await personalizationApi.outcome(
      { source_type: selectedTask.value.source_type, source_id: selectedTask.value.id },
      {
        terminal_state: outcome.terminal_state,
        actual_active_minutes: outcome.minutes || null,
        progress_ratio: outcome.progress / 100,
        reason_code: outcome.reason || null,
        completed_at: outcome.terminal_state === 'completed' ? new Date().toISOString() : null,
      },
    )
    outcomeOpen.value = false
    notify(t('personalization.outcomeSaved'), { type: 'success' })
  } catch (err) {
    error.value = err?.message || t('personalization.outcomeSaveFailed')
  } finally {
    busy.value = false
  }
}

watch(taskOptions, (list) => {
  if (!selectedKey.value && list.length) selectedKey.value = list[0].key
})
let timer
onMounted(() => {
  load()
  timer = window.setInterval(() => { tick.value = Date.now() }, 1000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<style scoped>
.work-controls { margin: 0 18px 14px; padding: 13px; border: 1px solid var(--ib-border); border-radius: var(--ib-radius-md); background: var(--ib-surface-subtle); }
.work-controls__title { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
.work-controls__title div { display: grid; }
.work-controls__title strong { color: var(--ib-text); }
.work-controls__title span { color: var(--ib-text-muted); font-size: 10px; }
.timer { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 10px 0; color: var(--ib-text-secondary); font-size: 11px; }
.timer strong { color: var(--ib-text); font-variant-numeric: tabular-nums; font-size: 17px; }
.timer span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.work-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.progress-field { display: flex; align-items: center; justify-content: space-between; color: var(--ib-text-secondary); font-size: 12px; }
.progress-field strong { color: var(--ib-text); }
@media (max-width: 520px) { .work-controls { margin-inline: 10px; } }
</style>
