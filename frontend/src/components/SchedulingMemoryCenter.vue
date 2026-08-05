<template>
  <section aria-labelledby="memory-center-title">
    <div class="memory-heading">
      <div><h2 id="memory-center-title">学习记忆中心</h2><p>这里展示 AI 可以用于估时与解释的记忆。自动总结只是可撤回的假设。</p></div>
      <v-btn variant="outlined" prepend-icon="mdi-download-outline" @click="downloadExport">导出</v-btn>
    </div>
    <div class="filters" role="search" aria-label="筛选学习记忆">
      <v-text-field v-model="filters.search" label="搜索" prepend-inner-icon="mdi-magnify" density="compact" variant="outlined" hide-details clearable @keyup.enter="load(true)" />
      <v-select v-model="filters.tier" :items="tierOptions" label="层级" density="compact" variant="outlined" hide-details clearable />
      <v-select v-model="filters.source" :items="sourceOptions" label="来源" density="compact" variant="outlined" hide-details clearable />
      <v-select v-model="filters.status" :items="statusOptions" label="状态" density="compact" variant="outlined" hide-details />
      <v-btn icon="mdi-refresh" variant="text" aria-label="刷新记忆" @click="load(true)" />
    </div>
    <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-3">{{ error }} <button class="text-button" @click="load(true)">重试</button></v-alert>
    <v-progress-linear v-if="loading" indeterminate color="primary" />
    <div v-if="!loading && !items.length" class="empty-state"><v-icon icon="mdi-brain" size="44" /><strong>暂时没有符合条件的记忆</strong><span>继续使用任务和可选计时后，这里会逐步出现有证据的总结。</span></div>
    <div v-else class="memory-list" aria-live="polite">
      <article v-for="item in items" :key="item.memory_id" class="memory-card">
        <div class="memory-card__top">
          <div class="chips"><v-chip size="x-small" variant="tonal">{{ tierLabel(item.tier) }}</v-chip><v-chip size="x-small" variant="outlined">{{ sourceLabel(item.source) }}</v-chip><v-chip size="x-small" :color="item.status === 'current' ? 'success' : 'grey'" variant="tonal">{{ statusLabel(item.status) }}</v-chip></div>
          <div><v-btn v-if="item.editable" icon="mdi-pencil-outline" size="small" variant="text" aria-label="编辑记忆" @click="openEdit(item)" /><v-btn v-if="item.deletable" icon="mdi-delete-outline" color="error" size="small" variant="text" aria-label="删除并阻止同一总结再次出现" @click="remove(item)" /></div>
        </div>
        <h3>{{ item.display_text }}</h3>
        <div class="memory-meta"><span>证据 {{ item.evidence_count }} 条</span><span v-if="item.confidence != null">置信度 {{ percent(item.confidence) }}</span><span>{{ dateRange(item) }}</span></div>
      </article>
    </div>
    <v-btn v-if="nextCursor" block variant="text" :loading="loadingMore" @click="load(false)">加载更多</v-btn>

    <div class="danger-zone">
      <div><strong>重置个性化模型</strong><p>清除模型和衍生记忆。你可选择是否用仍保留且合规的证据重新构建。</p><small>删除传播状态：{{ deletionState }}</small></div>
      <v-checkbox v-model="rebuild" label="之后从保留证据重新学习" hide-details density="compact" />
      <v-btn color="error" variant="outlined" :loading="resetting" @click="resetModel">重置</v-btn>
    </div>

    <v-dialog v-model="editOpen" max-width="560">
      <v-card rounded="xl"><v-card-title>编辑明确记忆</v-card-title><v-card-text><v-textarea v-model="editText" label="记忆内容" variant="outlined" counter="1000" /><div class="date-grid"><v-text-field v-model="editFrom" type="date" label="生效日期" variant="outlined" /><v-text-field v-model="editUntil" type="date" label="结束日期" variant="outlined" /></div></v-card-text><v-card-actions><v-spacer /><v-btn variant="text" @click="editOpen = false">取消</v-btn><v-btn color="primary" :loading="editing" @click="saveEdit">保存</v-btn></v-card-actions></v-card>
    </v-dialog>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { personalizationApi } from '@/services/personalization'

const filters = reactive({ search: '', tier: '', source: '', status: 'current' })
const items = ref([]); const nextCursor = ref(null); const loading = ref(true); const loadingMore = ref(false)
const error = ref(''); const deletionState = ref('unknown'); const rebuild = ref(false); const resetting = ref(false)
const editOpen = ref(false); const editing = ref(false); const editItem = ref(null); const editText = ref(''); const editFrom = ref(''); const editUntil = ref('')
const tierOptions = [{ title: '用户明确设置', value: 'explicit_declaration' }, { title: 'AI 证据总结', value: 'llm_reflection' }, { title: '临时情境', value: 'temporary_context' }]
const sourceOptions = [{ title: '用户', value: 'user' }, { title: 'AI', value: 'llm' }, { title: '会话', value: 'session' }]
const statusOptions = [{ title: '当前', value: 'current' }, { title: '已删除', value: 'deleted' }, { title: '已取代', value: 'superseded' }, { title: '已过期', value: 'expired' }, { title: '有矛盾', value: 'contradicted' }]
const labels = Object.fromEntries([...tierOptions, ...sourceOptions, ...statusOptions].map(x => [x.value, x.title]))
const tierLabel = value => labels[value] || value; const sourceLabel = value => labels[value] || value; const statusLabel = value => labels[value] || value
const percent = value => `${Math.round(Number(value) * 100)}%`
const dateRange = item => item.valid_from || item.valid_until ? `${item.valid_from || '最早'} → ${item.valid_until || '持续'}` : '长期有效'

async function load(reset = true) {
  if (reset) { loading.value = true; items.value = []; nextCursor.value = null } else loadingMore.value = true
  error.value = ''
  try {
    const result = await personalizationApi.memories({ ...filters, before: reset ? '' : nextCursor.value, limit: 30 })
    items.value = reset ? result.items : [...items.value, ...result.items]
    nextCursor.value = result.next_cursor
  } catch (err) { error.value = err?.message || '无法加载记忆。' }
  finally { loading.value = false; loadingMore.value = false }
}

function openEdit(item) { editItem.value = item; editText.value = item.display_text; editFrom.value = item.valid_from || ''; editUntil.value = item.valid_until || ''; editOpen.value = true }
async function saveEdit() {
  editing.value = true; error.value = ''
  try { await personalizationApi.editMemory(editItem.value.memory_id, { display_text: editText.value, valid_from: editFrom.value || null, valid_until: editUntil.value || null }); editOpen.value = false; await load(true) }
  catch (err) { error.value = err?.message || '编辑失败。' }
  finally { editing.value = false }
}
async function remove(item) {
  if (!window.confirm('删除这条记忆？AI 总结会留下抑制标记，避免同一内容立即再次出现。')) return
  try { await personalizationApi.deleteMemory(item.memory_id); await load(true); await loadDeletionStatus() }
  catch (err) { error.value = err?.message || '删除失败。' }
}
async function downloadExport() {
  try { const data = await personalizationApi.exportMemory(); const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `ibuddy-personalization-${new Date().toISOString().slice(0, 10)}.json`; a.click(); URL.revokeObjectURL(url) }
  catch (err) { error.value = err?.message || '导出失败。' }
}
async function resetModel() {
  if (!window.confirm('确认重置个性化模型和衍生记忆？基础任务与日历不会被删除。')) return
  resetting.value = true
  try { const settings = await personalizationApi.settings(); await personalizationApi.reset(settings, rebuild.value); await Promise.all([load(true), loadDeletionStatus()]) }
  catch (err) { error.value = err?.message || '重置失败。' }
  finally { resetting.value = false }
}
async function loadDeletionStatus() { try { deletionState.value = (await personalizationApi.deletionStatus()).state } catch { deletionState.value = 'unknown' } }
let filterTimer
watch(() => [filters.tier, filters.source, filters.status], () => load(true))
watch(() => filters.search, () => { clearTimeout(filterTimer); filterTimer = setTimeout(() => load(true), 300) })
onMounted(() => { load(true); loadDeletionStatus() })
</script>

<style scoped>
.memory-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding-bottom: 18px; border-bottom: 1px solid #e9ecf2; }.memory-heading h2 { margin: 0; font-size: 21px; }.memory-heading p,.danger-zone p { margin: 5px 0 0; color: #747e90; font-size: 12px; }
.filters { display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr auto; gap: 8px; margin: 18px 0; }.memory-list { display: grid; gap: 10px; }.memory-card { padding: 15px; border: 1px solid #e6eaf1; border-radius: 14px; background: #fff; }.memory-card__top { display: flex; justify-content: space-between; gap: 10px; }.chips { display: flex; flex-wrap: wrap; gap: 6px; }.memory-card h3 { margin: 10px 0 8px; font-size: 14px; line-height: 1.55; }.memory-meta { display: flex; flex-wrap: wrap; gap: 14px; color: #7b8494; font-size: 11px; }.empty-state { display: grid; justify-items: center; gap: 7px; padding: 48px 20px; color: #778195; text-align: center; }.danger-zone { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 14px; margin-top: 28px; padding: 16px; border: 1px solid #f0c7c7; border-radius: 14px; background: #fffafa; }.danger-zone small { color: #8c6670; }.date-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }.text-button { border: 0; background: none; text-decoration: underline; cursor: pointer; }
@media (max-width: 760px) { .filters { grid-template-columns: 1fr 1fr; }.filters > :first-child { grid-column: 1/-1; }.danger-zone { grid-template-columns: 1fr; }.memory-heading { align-items: center; } }
</style>
