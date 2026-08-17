<template>
  <article class="explanation-card" aria-labelledby="recommendation-explanation-title">
    <div class="explanation-head">
      <div>
        <h3 id="recommendation-explanation-title">{{ $t('personalization.explanationTitle') }}</h3>
        <p>{{ $t('personalization.explanationSubtitle') }}</p>
      </div>
      <v-chip size="small" :color="modeColor" variant="tonal">{{ modeLabel }}</v-chip>
    </div>
    <div class="explanation-grid">
      <section class="explanation-section deterministic">
        <div class="section-label"><v-icon icon="mdi-shield-check-outline" size="17" />{{ $t('personalization.deterministicBaseline') }}</div>
        <strong>{{ baselineDate || $t('personalization.deterministicGenerated') }}</strong>
        <ul><li v-for="reason in deterministicReasons" :key="reason">{{ reasonLabel(reason) }}</li></ul>
        <small>{{ $t('personalization.deterministicHelp') }}</small>
      </section>
      <section class="explanation-section personal">
        <div class="section-label"><v-icon icon="mdi-account-heart-outline" size="17" />{{ $t('personalization.personalSignals') }}</div>
        <div class="rank-row">
          <span>{{ $t('personalization.baselineRank', { n: personal.baseline_rank || 1 }) }}</span>
          <v-icon icon="mdi-arrow-right" size="15" />
          <span>{{ $t('personalization.suggestedRank', { n: personal.personalized_rank || personal.baseline_rank || 1 }) }}</span>
        </div>
        <div v-if="range.p50_minutes" class="range">
          <strong>{{ $t('personalization.minuteRange', { min: Math.round(range.p50_minutes), max: Math.round(range.p90_minutes) }) }}</strong>
          <span>{{ $t('personalization.estimateNotPromise') }}</span>
        </div>
        <div class="evidence">
          <v-chip v-for="item in (personal.evidence_categories || []).slice(0, 4)" :key="item" size="x-small" variant="outlined">
            {{ evidenceLabel(item) }}
          </v-chip>
          <span v-if="!personal.evidence_categories?.length">{{ $t('personalization.noPersonalEvidence') }}</span>
        </div>
      </section>
    </div>
    <v-alert v-if="limitations.length" type="warning" variant="tonal" density="compact" class="mt-3">{{ limitations[0] }}</v-alert>
    <div class="explanation-footer">
      <span>{{ $t('personalization.adjustmentSummary', { adjustment: formatAdjustment(personal.learned_adjustment), maturity: percent(personal.maturity), calibration: calibrationLabel }) }}</span>
      <strong>{{ $t('personalization.neverAutoApply') }}</strong>
    </div>
    <div v-if="alternatives.length" class="alternatives">
      <span>{{ $t('personalization.youCanChoose') }}</span>
      <button v-for="alternative in alternatives" :key="alternative" type="button" @click="$emit('choose', alternative)">
        {{ formatAlternative(alternative) }}
      </button>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({ explanation: { type: Object, default: () => ({}) } })
defineEmits(['choose'])
const { t, te } = useI18n()
const deterministic = computed(() => props.explanation.deterministic || {})
const personal = computed(() => props.explanation.personalization || {})
const range = computed(() => props.explanation.estimate_range || {})
const uncertainty = computed(() => props.explanation.uncertainty || {})
const alternatives = computed(() => props.explanation.alternatives?.display_order || [])
const baselineDate = computed(() => deterministic.value.date)
const deterministicReasons = computed(() => deterministic.value.reason_codes?.length
  ? deterministic.value.reason_codes
  : ['default_safe'])
const limitations = computed(() => uncertainty.value.limitations || [])
const modeLabel = computed(() => t(`personalization.mode.${personal.value.serving_mode || 'disabled'}`))
const modeColor = computed(() => ({ suggestion: 'success', shadow: 'info', killed: 'warning' }[personal.value.serving_mode] || 'grey'))
const calibrationLabel = computed(() => t(`personalization.calibrationState.${personal.value.calibration_state || 'unknown'}`))
const percent = (value) => `${Math.round(Number(value || 0) * 100)}%`
const formatAdjustment = (value) => Number(value || 0) === 0 ? t('personalization.none') : Number(value).toFixed(3)
const translated = (group, value) => {
  const key = `personalization.${group}.${value}`
  return te(key) ? t(key) : value
}
const reasonLabel = (value) => translated('reason', value)
const evidenceLabel = (value) => translated('evidenceType', value)
const formatAlternative = (value) => String(value).replace(/^date:/, '')
</script>

<style scoped>
.explanation-card { padding: 17px; border: 1px solid var(--ib-border); border-radius: var(--ib-radius-md); background: var(--ib-surface); }
.explanation-head { display: flex; justify-content: space-between; gap: 12px; }
.explanation-head h3 { margin: 0; color: var(--ib-text); font-size: 15px; }
.explanation-head p { margin: 5px 0 0; color: var(--ib-text-secondary); font-size: 12px; }
.explanation-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 14px; }
.explanation-section { padding: 13px; border: 1px solid var(--ib-border); border-left: 3px solid var(--ib-primary); border-radius: var(--ib-radius-sm); background: var(--ib-surface-subtle); }
.personal { border-left-color: var(--ib-info); }
.section-label { display: flex; align-items: center; gap: 5px; margin-bottom: 8px; color: var(--ib-text-secondary); font-size: 12px; font-weight: 700; }
.explanation-section strong { color: var(--ib-text); font-size: 16px; }
.explanation-section ul { margin: 8px 0; padding-left: 17px; color: var(--ib-text-secondary); font-size: 12px; line-height: 1.7; }
.explanation-section small { color: var(--ib-text-muted); font-size: 11px; }
.rank-row { display: flex; align-items: center; gap: 6px; color: var(--ib-text-secondary); font-size: 12px; }
.range { display: grid; gap: 2px; margin-top: 12px; }
.range span { color: var(--ib-text-muted); font-size: 11px; }
.evidence { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 12px; color: var(--ib-text-muted); font-size: 11px; }
.explanation-footer { display: flex; justify-content: space-between; gap: 10px; margin-top: 13px; color: var(--ib-text-secondary); font-size: 11px; }
.explanation-footer strong { color: var(--ib-success); }
.alternatives { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 12px; color: var(--ib-text-secondary); font-size: 12px; }
.alternatives button { padding: 5px 9px; border: 1px solid var(--ib-border); border-radius: 8px; color: var(--ib-primary-strong); background: var(--ib-surface); cursor: pointer; }
.alternatives button:hover { border-color: var(--ib-primary); background: var(--ib-primary-soft); }
@media (max-width: 650px) { .explanation-grid { grid-template-columns: 1fr; } .explanation-footer { align-items: flex-start; flex-direction: column; } }
</style>
