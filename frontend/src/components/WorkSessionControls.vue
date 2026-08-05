<template>
  <section class="work-controls" aria-labelledby="work-controls-title">
    <div class="work-controls__title"><div><strong id="work-controls-title">可选专注记录</strong><span>只记录你主动提交的时间与进度</span></div><v-chip size="x-small" :color="stateColor" variant="tonal">{{ stateLabel }}</v-chip></div>
    <v-alert v-if="captureDisabled" type="info" density="compact" variant="tonal">专注记录未开启。可在“设置 → 个性化”中单独启用。</v-alert>
    <template v-else>
      <v-select v-model="selectedKey" :items="taskOptions" item-title="title" item-value="key" label="选择任务" density="compact" variant="outlined" hide-details :disabled="Boolean(session)" />
      <div class="timer" aria-live="polite"><strong>{{ elapsedLabel }}</strong><span v-if="selectedTask">{{ selectedTask.title }}</span></div>
      <div class="work-actions">
        <v-btn v-if="!session" size="small" color="primary" prepend-icon="mdi-play" :disabled="!selectedTask" :loading="busy" @click="start">开始</v-btn>
        <v-btn v-else-if="session.state === 'active'" size="small" variant="tonal" prepend-icon="mdi-pause" :loading="busy" @click="transition('pause')">暂停</v-btn>
        <v-btn v-else size="small" variant="tonal" prepend-icon="mdi-play" :loading="busy" @click="transition('resume')">继续</v-btn>
        <v-btn v-if="session" size="small" color="primary" variant="outlined" prepend-icon="mdi-stop" :loading="busy" @click="transition('stop')">停止</v-btn>
        <v-btn v-if="selectedTask" size="small" variant="text" @click="outcomeOpen = true">填写结果</v-btn>
      </div>
    </template>
    <v-alert v-if="error" type="error" density="compact" variant="tonal" class="mt-2">{{ error }}</v-alert>

    <v-dialog v-model="outcomeOpen" max-width="470">
      <v-card rounded="xl"><v-card-title>记录实际结果</v-card-title><v-card-text><v-select v-model="outcome.terminal_state" :items="outcomeOptions" label="结果" variant="outlined" /><v-slider v-model="outcome.progress" label="完成进度" :min="0" :max="100" step="5" thumb-label /><v-text-field v-model.number="outcome.minutes" type="number" min="0" max="100000" label="实际投入分钟（可选）" variant="outlined" /><v-textarea v-if="outcome.terminal_state === 'reasonably_abandoned'" v-model="outcome.reason" label="合理放弃原因（可选）" variant="outlined" counter="64" /></v-card-text><v-card-actions><v-spacer/><v-btn variant="text" @click="outcomeOpen=false">取消</v-btn><v-btn color="primary" :loading="busy" @click="submitOutcome">保存</v-btn></v-card-actions></v-card>
    </v-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { parseServerTimestamp, personalizationApi } from '@/services/personalization'
const props = defineProps({ tasks: { type: Array, default: () => [] } })
const settings = ref(null); const session = ref(null); const selectedKey = ref(''); const busy = ref(false); const error = ref(''); const tick = ref(Date.now()); const outcomeOpen = ref(false)
const outcome = reactive({ terminal_state: 'completed', progress: 100, minutes: null, reason: '' })
const outcomeOptions = [{ title: '已完成', value: 'completed' }, { title: '合理放弃', value: 'reasonably_abandoned' }, { title: '确认错过截止', value: 'confirmed_miss' }, { title: '结果未知', value: 'unknown' }]
const taskOptions = computed(() => props.tasks.map(item => ({ ...item, key: `${item.source_type}:${item.id}` })))
const selectedTask = computed(() => taskOptions.value.find(item => item.key === selectedKey.value) || null)
const captureDisabled = computed(() => !settings.value?.effective?.work_session_capture)
const stateLabel = computed(() => captureDisabled.value ? '未启用' : session.value?.state === 'paused' ? '已暂停' : session.value ? '计时中' : '待开始')
const stateColor = computed(() => captureDisabled.value ? 'grey' : session.value?.state === 'paused' ? 'warning' : session.value ? 'success' : 'primary')
const elapsedSeconds = computed(() => { if (!session.value) return 0; const base = Number(session.value.accumulated_active_seconds || 0); if (session.value.state !== 'active') return base; const startedAt = parseServerTimestamp(session.value.started_at); return base + (Number.isFinite(startedAt) ? Math.max(0, Math.floor((tick.value - startedAt) / 1000)) : 0) })
const elapsedLabel = computed(() => { const seconds = elapsedSeconds.value; return `${String(Math.floor(seconds / 3600)).padStart(2,'0')}:${String(Math.floor((seconds % 3600) / 60)).padStart(2,'0')}:${String(seconds % 60).padStart(2,'0')}` })
async function load() { try { const [settingResult, active] = await Promise.all([personalizationApi.settings(), personalizationApi.activeSessions()]); settings.value = settingResult; session.value = active.items[0] || null; if (session.value) selectedKey.value = `${session.value.source.source_type}:${session.value.source.source_id}`; else if (!selectedKey.value && taskOptions.value.length) selectedKey.value = taskOptions.value[0].key } catch (err) { error.value = err?.message || '无法加载专注记录。' } }
async function start() { if (!selectedTask.value) return; busy.value = true; error.value=''; try { const result = await personalizationApi.startSession({ source_type: selectedTask.value.source_type, source_id: selectedTask.value.id }); session.value = result.session } catch(err){ error.value=err?.message||'开始失败。' } finally{busy.value=false} }
async function transition(action) { busy.value=true;error.value='';try{const result=await personalizationApi.transitionSession(session.value.id,action);session.value=result.session?.state==='stopped'?null:result.session}catch(err){error.value=err?.message||'操作失败。'}finally{busy.value=false} }
async function submitOutcome(){if(!selectedTask.value)return;busy.value=true;error.value='';try{await personalizationApi.outcome({source_type:selectedTask.value.source_type,source_id:selectedTask.value.id},{terminal_state:outcome.terminal_state,actual_active_minutes:outcome.minutes||null,progress_ratio:outcome.progress/100,reason_code:outcome.reason||null,completed_at:outcome.terminal_state==='completed'?new Date().toISOString():null});outcomeOpen.value=false}catch(err){error.value=err?.message||'结果保存失败。'}finally{busy.value=false}}
watch(taskOptions, list => { if (!selectedKey.value && list.length) selectedKey.value=list[0].key })
let timer; onMounted(()=>{load();timer=setInterval(()=>{tick.value=Date.now()},1000)});onBeforeUnmount(()=>clearInterval(timer))
</script>

<style scoped>
.work-controls{margin:0 18px 14px;padding:13px;border:1px solid #e5e9f2;border-radius:15px;background:#f9faff}.work-controls__title{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}.work-controls__title div{display:grid}.work-controls__title span{color:#7b8494;font-size:10px}.timer{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:10px 0;color:#59647a;font-size:11px}.timer strong{font-variant-numeric:tabular-nums;font-size:17px;color:#222c42}.timer span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.work-actions{display:flex;flex-wrap:wrap;gap:6px}
</style>
