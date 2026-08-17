<template>
  <section aria-labelledby="personalization-dashboard-title">
    <div class="dashboard-heading">
      <div>
        <h2 id="personalization-dashboard-title">{{ $t('personalization.dashboardTitle') }}</h2>
        <p>{{ $t('personalization.dashboardSubtitle') }}</p>
      </div>
      <v-btn icon="mdi-refresh" variant="text" :aria-label="$t('personalization.refreshDashboard')" @click="load" />
    </div>
    <v-alert v-if="error" type="error" variant="tonal" density="compact" class="my-4">
      {{ error }}
      <template #append><v-btn size="small" variant="text" @click="load">{{ $t('common.retry') }}</v-btn></template>
    </v-alert>
    <v-skeleton-loader v-if="loading" type="card@3" />

    <template v-else-if="data">
      <div class="summary-grid">
        <article class="metric-card">
          <span>{{ $t('personalization.maturity') }}</span>
          <strong>{{ percent(data.maturity.score) }}</strong>
          <v-progress-linear :model-value="data.maturity.score * 100" height="7" rounded color="primary" />
          <small>{{ maturityLabel }} · {{ $t('personalization.effectiveSamples', { n: data.maturity.effective_sample_size }) }}</small>
        </article>
        <article class="metric-card">
          <span>{{ $t('personalization.recentEffortRange') }}</span>
          <strong v-if="data.effort_range.p50_minutes">
            {{ minutes(data.effort_range.p50_minutes) }}–{{ minutes(data.effort_range.p90_minutes) }}
          </strong>
          <strong v-else>{{ $t('personalization.noRange') }}</strong>
          <small>{{ $t('personalization.rangeHelp') }}</small>
        </article>
        <article class="metric-card">
          <span>{{ $t('personalization.availableEvidence') }}</span>
          <strong>{{ data.evidence.eligible_outcomes }}</strong>
          <small>{{ $t('personalization.evidenceSummary', { scopes: data.evidence.feature_scopes, links: data.evidence.memory_evidence_links }) }}</small>
        </article>
        <article class="metric-card">
          <span>{{ $t('personalization.privacyState') }}</span>
          <strong>{{ data.privacy.operational_personalization_enabled ? $t('common.enabled') : $t('common.disabled') }}</strong>
          <small>{{ privacySummary }}</small>
        </article>
      </div>

      <article class="chart-card">
        <div><h3>{{ $t('personalization.estimateVsActual') }}</h3><p>{{ $t('personalization.chartHelp') }}</p></div>
        <div v-if="!trend.length" class="no-data">{{ $t('personalization.trendEmpty') }}</div>
        <div v-else class="chart-scroll">
          <svg class="trend-chart" viewBox="0 0 720 230" role="img" aria-labelledby="trend-title trend-desc">
            <title id="trend-title">{{ $t('personalization.trendTitle') }}</title>
            <desc id="trend-desc">{{ $t('personalization.trendDescription') }}</desc>
            <defs>
              <pattern id="estimatePattern" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="8" height="8" fill="var(--ib-primary-soft)" />
                <line x1="0" y1="0" x2="0" y2="8" stroke="var(--ib-primary)" stroke-width="3" />
              </pattern>
            </defs>
            <line x1="42" y1="190" x2="700" y2="190" stroke="var(--ib-border-strong)" stroke-width="1" />
            <g v-for="(point, index) in chartPoints" :key="`${point.date}-${index}`">
              <rect :x="point.x" :y="point.estimatedY" width="16" :height="190 - point.estimatedY" fill="url(#estimatePattern)" />
              <rect :x="point.x + 20" :y="point.actualY" width="16" :height="190 - point.actualY" fill="var(--ib-primary)" />
              <text :x="point.x + 18" y="210" text-anchor="middle" font-size="10" fill="var(--ib-text-secondary)">{{ shortDate(point.date) }}</text>
            </g>
          </svg>
        </div>
        <div v-if="trend.length" class="legend">
          <span><i class="estimate-key" />{{ $t('personalization.estimated') }}</span>
          <span><i class="actual-key" />{{ $t('personalization.actual') }}</span>
        </div>
        <div class="table-wrap">
          <table>
            <caption class="sr-only">{{ $t('personalization.trendTable') }}</caption>
            <thead><tr><th>{{ $t('personalization.date') }}</th><th>{{ $t('personalization.source') }}</th><th>{{ $t('personalization.estimated') }}</th><th>{{ $t('personalization.actual') }}</th><th>{{ $t('personalization.outcome') }}</th></tr></thead>
            <tbody>
              <tr v-for="(point, index) in trend" :key="index">
                <td>{{ point.date }}</td><td>{{ sourceLabel(point.source_type) }}</td>
                <td>{{ point.estimated_minutes ? minutes(point.estimated_minutes) : '—' }}</td>
                <td>{{ minutes(point.actual_minutes) }}</td><td>{{ outcomeLabel(point.terminal_state) }}</td>
              </tr>
              <tr v-if="!trend.length"><td colspan="5">{{ $t('personalization.noData') }}</td></tr>
            </tbody>
          </table>
        </div>
      </article>

      <div class="detail-grid">
        <article class="chart-card">
          <h3>{{ $t('personalization.calibration') }}</h3>
          <template v-if="data.calibration.visible">
            <strong class="large-number">{{ percent(data.calibration.expected_calibration_error) }}</strong>
            <p>{{ $t('personalization.calibrationHelp', { n: data.calibration.n }) }}</p>
          </template>
          <div v-else class="no-data">{{ $t('personalization.calibrationHidden', { minimum: data.calibration.minimum_n, current: data.calibration.n }) }}</div>
        </article>
        <article class="chart-card">
          <h3>{{ $t('personalization.modelHistory') }}</h3>
          <ol v-if="data.model_history.length" class="history">
            <li v-for="model in data.model_history" :key="model.model_id">
              <span>{{ model.model_type }} · {{ model.lifecycle }}</span>
              <small>{{ model.algorithm_version }} · n={{ model.effective_sample_size }}</small>
            </li>
          </ol>
          <div v-else class="no-data">{{ $t('personalization.modelHistoryEmpty') }}</div>
        </article>
      </div>
      <RecommendationExplanationCard :explanation="explanation" />
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { personalizationApi } from '@/services/personalization'
import RecommendationExplanationCard from '@/components/RecommendationExplanationCard.vue'

const { t, te } = useI18n()
const loading = ref(true)
const error = ref('')
const data = ref(null)
const trend = computed(() => data.value?.estimate_actual_trend || [])
const explanation = computed(() => ({
  deterministic: {
    date: data.value?.effort_range?.as_of ? String(data.value.effort_range.as_of).slice(0, 10) : null,
    reason_codes: ['capacity_safe', 'deadline_safe'],
  },
  personalization: {
    serving_mode: data.value?.privacy?.runtime?.serving_mode || 'disabled',
    baseline_rank: 1,
    personalized_rank: 1,
    learned_adjustment: 0,
    maturity: data.value?.maturity?.score || 0,
    calibration_state: data.value?.calibration?.visible ? 'calibrated' : 'insufficient',
    evidence_categories: data.value?.evidence?.eligible_outcomes ? ['eligible_outcomes'] : [],
  },
  estimate_range: data.value?.effort_range || {},
  uncertainty: { limitations: [t('personalization.dashboardLimitation')] },
  alternatives: { display_order: [t('personalization.keepBaseline')] },
}))
const maturityLabel = computed(() => t(`personalization.maturityState.${data.value?.maturity?.state || 'cold_start'}`))
const privacySummary = computed(() => {
  const privacy = data.value?.privacy
  if (!privacy?.operational_personalization_enabled) return t('personalization.allLearningOff')
  const active = [
    privacy.work_session_capture_enabled && t('personalization.privacyTimer'),
    privacy.llm_memory_enabled && t('personalization.privacyMemory'),
    privacy.cross_user_learning_enabled && t('personalization.privacyAggregate'),
  ].filter(Boolean)
  return active.length ? active.join(t('personalization.listSeparator')) : t('personalization.personalOnly')
})
const percent = (value) => `${Math.round(Number(value || 0) * 100)}%`
const minutes = (value) => t('personalization.minutes', { n: Math.round(Number(value || 0)) })
const shortDate = (value) => value ? value.slice(5) : '—'
const chartPoints = computed(() => {
  const shown = trend.value.slice(-10)
  const max = Math.max(1, ...shown.flatMap((item) => [item.estimated_minutes || 0, item.actual_minutes || 0]))
  const gap = 620 / Math.max(shown.length, 1)
  return shown.map((item, index) => ({
    ...item,
    x: 55 + index * gap,
    estimatedY: 190 - ((item.estimated_minutes || 0) / max) * 150,
    actualY: 190 - ((item.actual_minutes || 0) / max) * 150,
  }))
})

function translatedValue(group, value) {
  const key = `personalization.${group}.${value || 'unknown'}`
  return te(key) ? t(key) : (value || t('personalization.unknown'))
}
const sourceLabel = (value) => translatedValue('sourceType', value)
const outcomeLabel = (value) => translatedValue('outcomeState', value)

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await personalizationApi.dashboard()
  } catch (err) {
    error.value = err?.message || t('personalization.loadDashboardFailed')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.dashboard-heading { display: flex; justify-content: space-between; gap: 16px; padding-bottom: 18px; border-bottom: 1px solid var(--ib-border); }
.dashboard-heading h2 { margin: 0; color: var(--ib-text); font-size: 21px; }
.dashboard-heading p, .chart-card p { margin: 5px 0 0; color: var(--ib-text-secondary); font-size: 12px; }
.summary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }
.metric-card, .chart-card { padding: 17px; border: 1px solid var(--ib-border); border-radius: var(--ib-radius-md); background: var(--ib-surface); }
.metric-card { display: grid; gap: 8px; }
.metric-card > span { color: var(--ib-text-secondary); font-size: 12px; }
.metric-card strong { color: var(--ib-text); font-size: 23px; }
.metric-card small { color: var(--ib-text-muted); font-size: 11px; }
.chart-card { margin-bottom: 12px; }
.chart-card h3 { margin: 0; color: var(--ib-text); font-size: 15px; }
.chart-scroll { overflow-x: auto; }
.trend-chart { width: 100%; min-width: 560px; max-height: 260px; margin-top: 12px; }
.legend { display: flex; gap: 20px; color: var(--ib-text-secondary); font-size: 12px; }
.legend span { display: flex; align-items: center; gap: 6px; }
.legend i { width: 18px; height: 10px; border-radius: 2px; }
.estimate-key { background: repeating-linear-gradient(45deg, var(--ib-primary-soft) 0 4px, var(--ib-primary) 4px 6px); }
.actual-key { background: var(--ib-primary); }
.table-wrap { overflow-x: auto; margin-top: 14px; }
table { width: 100%; border-collapse: collapse; color: var(--ib-text); font-size: 12px; }
th, td { padding: 9px; border-bottom: 1px solid var(--ib-border); text-align: left; }
th { color: var(--ib-text-secondary); background: var(--ib-surface-subtle); }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.no-data { padding: 24px 8px; color: var(--ib-text-secondary); font-size: 12px; text-align: center; }
.large-number { display: block; margin-top: 18px; color: var(--ib-text); font-size: 30px; }
.history { max-height: 200px; overflow: auto; margin: 12px 0 0; padding-left: 20px; }
.history li { margin: 9px 0; }
.history span, .history small { display: block; }
.history small { color: var(--ib-text-muted); }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 650px) { .summary-grid, .detail-grid { grid-template-columns: 1fr; } }
</style>
