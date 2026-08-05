<template>
  <section aria-labelledby="personalization-settings-title">
    <div class="panel-heading">
      <div>
        <h2 id="personalization-settings-title">个性化与隐私</h2>
        <p>你可以分别决定系统能学习什么。关闭后，基础日历和确定性排期仍然可用。</p>
      </div>
      <v-chip :color="servingColor" variant="tonal" size="small">{{ servingLabel }}</v-chip>
    </div>

    <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-4">
      {{ error }} <button type="button" class="inline-action" @click="load">重试</button>
    </v-alert>
    <v-alert v-if="saved" type="success" variant="tonal" density="compact" class="mb-4">设置已在服务器保存。</v-alert>
    <v-skeleton-loader v-if="loading" type="list-item-three-line@4" />

    <template v-else>
      <div class="setting-row setting-row--primary">
        <div><strong>启用个性化建议</strong><p>根据你的历史调整耗时区间和安全候选的展示顺序；不会自动移动任务。</p></div>
        <v-switch v-model="form.operational_personalization_enabled" color="primary" hide-details aria-label="启用个性化建议" />
      </div>
      <div v-for="control in controls" :key="control.key" class="setting-row">
        <div><strong>{{ control.title }}</strong><p>{{ control.description }}</p></div>
        <v-switch v-model="form[control.key]" :disabled="!form.operational_personalization_enabled" color="primary" hide-details :aria-label="control.title" />
      </div>
      <div class="setting-row">
        <div><strong>原始事件保留时间</strong><p>到期后自动清理；衍生结果也受删除与重置控制。</p></div>
        <v-select v-model="form.raw_event_retention_days" :items="retentionOptions" item-title="title" item-value="value" density="compact" variant="outlined" hide-details class="retention-select" aria-label="原始事件保留时间" />
      </div>
      <div class="privacy-state" aria-live="polite">
        <span><v-icon icon="mdi-shield-check-outline" size="18" /> 确定性排期始终可用</span>
        <span>设置版本 {{ form.version || '—' }}</span>
        <span>策略 {{ form.policy_version }}</span>
      </div>
      <div class="actions">
        <span v-if="dirty" class="dirty-copy">有未保存的更改</span>
        <v-spacer />
        <v-btn variant="outlined" :disabled="saving || !dirty" @click="load">撤销</v-btn>
        <v-btn color="primary" :loading="saving" :disabled="!dirty" @click="save">保存隐私设置</v-btn>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { personalizationApi } from '@/services/personalization'

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
  runtime: {}, effective: {},
})

const controls = [
  { key: 'work_session_capture_enabled', title: '可选专注计时', description: '只有你主动开始计时或填写结果时才记录；不监控屏幕、键盘或其他 App。' },
  { key: 'llm_memory_enabled', title: 'AI 总结记忆', description: '允许 AI 把重复证据总结为可查看、可删除的假设；不会改写角色卡。' },
  { key: 'cross_user_learning_enabled', title: '贡献匿名聚合统计', description: '只贡献去标识的结构化统计，并执行最小人数保护；不共享任务原文。' },
  { key: 'near_tie_exploration_enabled', title: '近似方案顺序实验', description: '只在同样安全且差异很小的选项间随机展示顺序，绝不自动应用。' },
]
const retentionOptions = [
  { title: '90 天', value: 90 }, { title: '180 天', value: 180 },
  { title: '12 个月（推荐）', value: 365 }, { title: '24 个月', value: 730 },
]
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
const servingLabel = computed(() => ({ suggestion: '建议模式', shadow: '影子评估', replay: '回放', killed: '已安全关闭', disabled: '未启用' }[form.runtime?.serving_mode] || '状态未知'))
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
  loading.value = true; error.value = ''; saved.value = false
  try { apply(await personalizationApi.settings()) }
  catch (err) { error.value = err?.message || '无法加载设置。' }
  finally { loading.value = false }
}

async function save() {
  saving.value = true; error.value = ''; saved.value = false
  try { apply(await personalizationApi.saveSettings(form)); saved.value = true }
  catch (err) { error.value = err?.status === 409 ? '设置已在其他页面更新，请重新加载。' : (err?.message || '保存失败，原设置未改变。') }
  finally { saving.value = false }
}

defineExpose({ save, dirty })
onMounted(load)
</script>

<style scoped>
.panel-heading { display: flex; justify-content: space-between; gap: 18px; padding-bottom: 18px; border-bottom: 1px solid #e9ecf2; }
.panel-heading h2 { margin: 0; font-size: 21px; color: #202633; }
.panel-heading p, .setting-row p { margin: 5px 0 0; color: #747e90; font-size: 12px; line-height: 1.55; }
.setting-row { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 17px 0; border-bottom: 1px solid #eff1f4; }
.setting-row > div:first-child { max-width: 520px; }
.setting-row--primary { margin-top: 12px; }
.retention-select { max-width: 210px; }
.privacy-state { display: flex; flex-wrap: wrap; gap: 14px 24px; margin-top: 18px; padding: 12px 14px; border-radius: 12px; background: #f5f7fb; color: #4e596c; font-size: 12px; }
.privacy-state span { display: inline-flex; align-items: center; gap: 5px; }
.actions { display: flex; align-items: center; gap: 10px; margin-top: 22px; }
.dirty-copy { color: #8a6200; font-size: 12px; }
.inline-action { border: 0; color: inherit; text-decoration: underline; background: none; cursor: pointer; }
@media (max-width: 600px) { .panel-heading, .setting-row { align-items: flex-start; } .setting-row { gap: 10px; } .retention-select { max-width: 150px; } }
</style>
