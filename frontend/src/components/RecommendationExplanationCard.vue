<template>
  <article class="explanation-card" aria-labelledby="recommendation-explanation-title">
    <div class="explanation-head"><div><h3 id="recommendation-explanation-title">为什么是这个安排？</h3><p>确定性约束与个性化信号分开显示，便于你自己判断。</p></div><v-chip size="small" :color="modeColor" variant="tonal">{{ modeLabel }}</v-chip></div>
    <div class="explanation-grid">
      <section class="explanation-section deterministic"><div class="section-label"><v-icon icon="mdi-shield-check-outline" size="17" />确定性基线（排期权威）</div><strong>{{ baselineDate || '按确定性排期生成' }}</strong><ul><li v-for="reason in deterministicReasons" :key="reason">{{ reason }}</li></ul><small>容量、截止日期、依赖关系和锁定项由确定性排期器检查。</small></section>
      <section class="explanation-section personal"><div class="section-label"><v-icon icon="mdi-account-heart-outline" size="17" />个人信号（仅做提示）</div><div class="rank-row"><span>基线顺序 {{ personal.baseline_rank || 1 }}</span><v-icon icon="mdi-arrow-right" size="15" /><span>提示顺序 {{ personal.personalized_rank || personal.baseline_rank || 1 }}</span></div><div v-if="range.p50_minutes" class="range"><strong>{{ Math.round(range.p50_minutes) }}–{{ Math.round(range.p90_minutes) }} 分钟</strong><span>P50–P90 估计范围，不是承诺</span></div><div class="evidence"><v-chip v-for="item in (personal.evidence_categories || []).slice(0, 4)" :key="item" size="x-small" variant="outlined">{{ evidenceLabel(item) }}</v-chip><span v-if="!personal.evidence_categories?.length">暂无足够个人证据</span></div></section>
    </div>
    <v-alert v-if="limitations.length" type="warning" variant="tonal" density="compact" class="mt-3">{{ limitations[0] }}</v-alert>
    <div class="explanation-footer"><span>调整 {{ formatAdjustment(personal.learned_adjustment) }} · 成熟度 {{ percent(personal.maturity) }} · {{ calibrationLabel }}</span><strong>不会自动应用</strong></div>
    <div class="alternatives" v-if="alternatives.length"><span>你可以选择：</span><button v-for="alternative in alternatives" :key="alternative" type="button" @click="$emit('choose', alternative)">{{ formatAlternative(alternative) }}</button></div>
  </article>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ explanation: { type: Object, default: () => ({}) } })
defineEmits(['choose'])
const deterministic = computed(() => props.explanation.deterministic || {})
const personal = computed(() => props.explanation.personalization || {})
const range = computed(() => props.explanation.estimate_range || {})
const uncertainty = computed(() => props.explanation.uncertainty || {})
const alternatives = computed(() => props.explanation.alternatives?.display_order || [])
const baselineDate = computed(() => deterministic.value.date)
const deterministicReasons = computed(() => deterministic.value.reason_codes?.length ? deterministic.value.reason_codes : ['保持确定性可行性与截止日期安全'])
const limitations = computed(() => uncertainty.value.limitations || [])
const modeLabel = computed(() => ({ suggestion: '建议模式', shadow: '影子评估', replay: '回放', disabled: '仅确定性基线', killed: '安全关闭' }[personal.value.serving_mode] || '仅确定性基线'))
const modeColor = computed(() => ({ suggestion: 'success', shadow: 'info', killed: 'warning' }[personal.value.serving_mode] || 'grey'))
const calibrationLabel = computed(() => ({ calibrated: '校准充分', limited: '校准有限', insufficient: '校准不足' }[personal.value.calibration_state] || '校准未知'))
const percent = value => `${Math.round(Number(value || 0) * 100)}%`
const formatAdjustment = value => Number(value || 0) === 0 ? '无' : Number(value).toFixed(3)
const evidenceLabel = value => ({ active_timer: '主动计时', direct_duration: '直接时长', eligible_decision_history: '决策历史', eligible_outcomes: '合规结果', recent_decisions: '近期决策', subject_history: '科目历史', task_archetype_history: '任务类型历史' }[value] || value)
const formatAlternative = value => String(value).replace(/^date:/, '')
</script>

<style scoped>
.explanation-card{padding:17px;border:1px solid #e3e8f1;border-radius:15px;background:#fff}.explanation-head{display:flex;justify-content:space-between;gap:12px}.explanation-head h3{margin:0;font-size:15px}.explanation-head p{margin:5px 0 0;color:#747e90;font-size:12px}.explanation-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px}.explanation-section{padding:13px;border-radius:12px}.deterministic{background:#f4f7fc;border-left:3px solid #4f6fd2}.personal{background:#fbf7ff;border-left:3px solid #8a55c7}.section-label{display:flex;align-items:center;gap:5px;margin-bottom:8px;color:#4f5b70;font-size:12px;font-weight:700}.explanation-section strong{font-size:16px}.explanation-section ul{margin:8px 0;padding-left:17px;color:#5d687b;font-size:12px;line-height:1.7}.explanation-section small{color:#7d8797;font-size:11px}.rank-row{display:flex;align-items:center;gap:6px;color:#5c687b;font-size:12px}.range{display:grid;gap:2px;margin-top:12px}.range span{color:#7d8797;font-size:11px}.evidence{display:flex;flex-wrap:wrap;gap:5px;margin-top:12px}.explanation-footer{display:flex;justify-content:space-between;gap:10px;margin-top:13px;color:#6c7789;font-size:11px}.explanation-footer strong{color:#2e7d5b}.alternatives{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:12px;color:#6c7789;font-size:12px}.alternatives button{padding:5px 9px;border:1px solid #dbe1ec;border-radius:8px;background:#fff;color:#405fc1;cursor:pointer}.alternatives button:hover{background:#f2f5ff}@media(max-width:650px){.explanation-grid{grid-template-columns:1fr}.explanation-footer{align-items:flex-start;flex-direction:column}}
</style>
