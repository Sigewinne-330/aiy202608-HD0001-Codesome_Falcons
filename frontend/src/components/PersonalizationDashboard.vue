<template>
  <section aria-labelledby="personalization-dashboard-title">
    <div class="dashboard-heading"><div><h2 id="personalization-dashboard-title">个性化仪表盘</h2><p>只展示你的证据、模型成熟度和可解释区间，不用“能量值”给你贴标签。</p></div><v-btn icon="mdi-refresh" variant="text" aria-label="刷新仪表盘" @click="load" /></div>
    <v-alert v-if="error" type="error" variant="tonal" density="compact" class="my-4">{{ error }}</v-alert>
    <v-skeleton-loader v-if="loading" type="card@3" />
    <template v-else-if="data">
      <div class="summary-grid">
        <article class="metric-card"><span>学习成熟度</span><strong>{{ percent(data.maturity.score) }}</strong><v-progress-linear :model-value="data.maturity.score * 100" height="7" rounded color="primary" /><small>{{ maturityLabel }} · 有效样本 {{ data.maturity.effective_sample_size }}</small></article>
        <article class="metric-card"><span>最近耗时区间</span><strong v-if="data.effort_range.p50_minutes">{{ minutes(data.effort_range.p50_minutes) }}–{{ minutes(data.effort_range.p90_minutes) }}</strong><strong v-else>暂无区间</strong><small>P50 到 P90；P90 不是最晚完成时间</small></article>
        <article class="metric-card"><span>可用证据</span><strong>{{ data.evidence.eligible_outcomes }}</strong><small>{{ data.evidence.feature_scopes }} 个统计范围 · {{ data.evidence.memory_evidence_links }} 条记忆证据链接</small></article>
        <article class="metric-card"><span>当前隐私状态</span><strong>{{ data.privacy.operational_personalization_enabled ? '已启用' : '未启用' }}</strong><small>{{ privacySummary }}</small></article>
      </div>

      <article class="chart-card">
        <div><h3>估计与实际用时</h3><p>柱形使用不同纹理与标签，不只依赖颜色。下表包含同一数据。</p></div>
        <div v-if="!trend.length" class="no-data">至少记录一次可用的实际耗时后才会显示趋势。</div>
        <svg v-else class="trend-chart" viewBox="0 0 720 230" role="img" aria-labelledby="trend-title trend-desc">
          <title id="trend-title">估计与实际用时趋势图</title><desc id="trend-desc">每组左侧斜纹柱是估计分钟，右侧实心柱是实际分钟。</desc>
          <defs><pattern id="estimatePattern" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="8" height="8" fill="#dce5ff"/><line x1="0" y1="0" x2="0" y2="8" stroke="#476ad6" stroke-width="3"/></pattern></defs>
          <line x1="42" y1="190" x2="700" y2="190" stroke="#677184" stroke-width="1" />
          <g v-for="(point, index) in chartPoints" :key="`${point.date}-${index}`">
            <rect :x="point.x" :y="point.estimatedY" width="16" :height="190-point.estimatedY" fill="url(#estimatePattern)" />
            <rect :x="point.x+20" :y="point.actualY" width="16" :height="190-point.actualY" fill="#6f4cc3" />
            <text :x="point.x+18" y="210" text-anchor="middle" font-size="10" fill="#566075">{{ shortDate(point.date) }}</text>
          </g>
        </svg>
        <div v-if="trend.length" class="legend"><span><i class="estimate-key" />估计</span><span><i class="actual-key" />实际</span></div>
        <div class="table-wrap"><table><caption class="sr-only">估计与实际用时明细</caption><thead><tr><th>日期</th><th>来源</th><th>估计</th><th>实际</th><th>结果</th></tr></thead><tbody><tr v-for="(point, index) in trend" :key="index"><td>{{ point.date }}</td><td>{{ point.source_type }}</td><td>{{ point.estimated_minutes ? minutes(point.estimated_minutes) : '—' }}</td><td>{{ minutes(point.actual_minutes) }}</td><td>{{ point.terminal_state }}</td></tr><tr v-if="!trend.length"><td colspan="5">暂无数据</td></tr></tbody></table></div>
      </article>

      <div class="detail-grid">
        <article class="chart-card"><h3>校准</h3><template v-if="data.calibration.visible"><strong class="large-number">{{ percent(data.calibration.expected_calibration_error) }}</strong><p>期望校准误差，越低越好；样本 {{ data.calibration.n }}。</p></template><div v-else class="no-data">为避免小样本误导，满 {{ data.calibration.minimum_n }} 条评估记录后才显示校准值（当前 {{ data.calibration.n }}）。</div></article>
        <article class="chart-card"><h3>模型版本历史</h3><ol v-if="data.model_history.length" class="history"><li v-for="model in data.model_history" :key="model.model_id"><span>{{ model.model_type }} · {{ model.lifecycle }}</span><small>{{ model.algorithm_version }} · n={{ model.effective_sample_size }}</small></li></ol><div v-else class="no-data">尚未形成个人模型，当前使用版本化默认先验。</div></article>
      </div>
      <RecommendationExplanationCard :explanation="explanation" />
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { personalizationApi } from '@/services/personalization'
import RecommendationExplanationCard from '@/components/RecommendationExplanationCard.vue'
const loading = ref(true); const error = ref(''); const data = ref(null)
const trend = computed(() => data.value?.estimate_actual_trend || [])
const explanation = computed(() => ({
  deterministic: { date: data.value?.effort_range?.as_of ? String(data.value.effort_range.as_of).slice(0, 10) : null, reason_codes: ['capacity_safe', 'deadline_safe'] },
  personalization: { serving_mode: data.value?.privacy?.runtime?.serving_mode || 'disabled', baseline_rank: 1, personalized_rank: 1, learned_adjustment: 0, maturity: data.value?.maturity?.score || 0, calibration_state: data.value?.calibration?.visible ? 'calibrated' : 'insufficient', evidence_categories: data.value?.evidence?.eligible_outcomes ? ['eligible_outcomes'] : [] },
  estimate_range: data.value?.effort_range || {},
  uncertainty: { limitations: ['仪表盘展示的是最近个人预测；实际排期仍由确定性调度器负责。'] },
  alternatives: { display_order: ['date:保持基线'] },
}))
const maturityLabel = computed(() => ({ cold_start: '冷启动', developing: '学习中', calibrated: '已校准', stale: '已过期' }[data.value?.maturity?.state] || data.value?.maturity?.state || '冷启动'))
const privacySummary = computed(() => { const p = data.value?.privacy; if (!p?.operational_personalization_enabled) return '所有学习开关为关闭'; const active = [p.work_session_capture_enabled && '计时', p.llm_memory_enabled && 'AI 记忆', p.cross_user_learning_enabled && '匿名聚合'].filter(Boolean); return active.length ? active.join('、') : '仅个人基础学习' })
const percent = value => `${Math.round(Number(value || 0) * 100)}%`; const minutes = value => `${Math.round(Number(value || 0))} 分钟`; const shortDate = value => value ? value.slice(5) : '—'
const chartPoints = computed(() => { const shown = trend.value.slice(-10); const max = Math.max(1, ...shown.flatMap(x => [x.estimated_minutes || 0, x.actual_minutes || 0])); const gap = 620 / Math.max(shown.length, 1); return shown.map((x, i) => ({ ...x, x: 55 + i * gap, estimatedY: 190 - ((x.estimated_minutes || 0) / max) * 150, actualY: 190 - ((x.actual_minutes || 0) / max) * 150 })) })
async function load() { loading.value = true; error.value = ''; try { data.value = await personalizationApi.dashboard() } catch (err) { error.value = err?.message || '无法加载仪表盘。' } finally { loading.value = false } }
onMounted(load)
</script>

<style scoped>
.dashboard-heading { display:flex;justify-content:space-between;gap:16px;padding-bottom:18px;border-bottom:1px solid #e9ecf2}.dashboard-heading h2{margin:0;font-size:21px}.dashboard-heading p,.chart-card p{margin:5px 0 0;color:#747e90;font-size:12px}.summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:18px 0}.metric-card,.chart-card{padding:17px;border:1px solid #e5e9f1;border-radius:15px;background:#fff}.metric-card{display:grid;gap:8px}.metric-card>span{color:#667185;font-size:12px}.metric-card strong{font-size:23px}.metric-card small{color:#788295;font-size:11px}.chart-card{margin-bottom:12px}.chart-card h3{margin:0;font-size:15px}.trend-chart{width:100%;max-height:260px;margin-top:12px}.legend{display:flex;gap:20px;font-size:12px}.legend span{display:flex;align-items:center;gap:6px}.legend i{width:18px;height:10px;border-radius:2px}.estimate-key{background:repeating-linear-gradient(45deg,#dce5ff 0 4px,#476ad6 4px 6px)}.actual-key{background:#6f4cc3}.table-wrap{overflow-x:auto;margin-top:14px}table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:9px;border-bottom:1px solid #edf0f4;text-align:left}th{color:#5c6678;background:#f7f8fb}.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.no-data{padding:24px 8px;color:#7c8698;font-size:12px;text-align:center}.large-number{display:block;margin-top:18px;font-size:30px}.history{max-height:200px;overflow:auto;margin:12px 0 0;padding-left:20px}.history li{margin:9px 0}.history span,.history small{display:block}.history small{color:#7b8495}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:650px){.summary-grid,.detail-grid{grid-template-columns:1fr}.trend-chart{min-width:600px}.chart-card{overflow-x:auto}}
</style>
