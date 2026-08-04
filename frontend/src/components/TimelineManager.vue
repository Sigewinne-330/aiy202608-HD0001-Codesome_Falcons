<template>
  <section class="timeline-manager">
    <header class="timeline-header">
      <v-btn icon="mdi-arrow-left" variant="tonal" :aria-label="$t('progress.backCategory')" @click="$emit('back')" />
      <span class="timeline-icon" :style="{ background: categoryMeta.softColor, color: categoryMeta.color }">{{ categoryMeta.key }}</span>
      <div class="timeline-title">
        <div class="eyebrow">{{ $t('progress.timelineManager') }}</div>
        <h1>{{ timeline.title }}</h1>
        <p>{{ timeline.subject || $t('progress.noGroup') }}</p>
      </div>
      <div class="timeline-actions">
        <v-btn prepend-icon="mdi-creation-outline" color="primary" variant="tonal" @click="askAgent">
          {{ $t('progress.askAgent') }}
        </v-btn>
        <v-btn icon="mdi-pencil-outline" variant="text" :aria-label="$t('common.edit')" @click="openTimelineEdit" />
        <v-btn prepend-icon="mdi-plus" color="primary" variant="flat" @click="openAdd">
          {{ $t('progress.addMilestone') }}
        </v-btn>
      </div>
    </header>

    <div class="summary-grid">
      <v-card rounded="xl" elevation="0">
        <span>{{ $t('progress.progress') }}</span>
        <strong>{{ progress }}%</strong>
        <v-progress-linear :model-value="progress" :color="categoryMeta.vuetifyColor" height="7" rounded />
      </v-card>
      <v-card rounded="xl" elevation="0">
        <span>{{ $t('progress.currentRisk') }}</span>
        <strong :class="`risk-${riskLevel}`">{{ riskLabel }}</strong>
        <v-progress-linear :model-value="risk" :color="riskColor" height="7" rounded />
      </v-card>
      <v-card rounded="xl" elevation="0">
        <span>{{ $t('progress.milestones') }}</span>
        <strong>{{ doneCount }}/{{ milestones.length }}</strong>
        <small>{{ $t('progress.completedCount') }}</small>
      </v-card>
      <v-card rounded="xl" elevation="0">
        <span>{{ $t('progress.nextDeadline') }}</span>
        <strong class="next-date">{{ nextMilestone ? formatDate(nextMilestone.deadline) : '—' }}</strong>
        <small>{{ nextMilestone?.title || $t('progress.noUpcoming') }}</small>
      </v-card>
    </div>

    <div class="calendar-sync-note">
      <v-icon icon="mdi-calendar-check-outline" size="16" />
      {{ $t('progress.calendarAutoSync') }}
    </div>

    <v-card class="milestone-card" rounded="xl" elevation="0">
      <div class="milestone-card__header">
        <div>
          <h2>{{ $t('progress.timeline') }}</h2>
          <p>{{ $t('progress.timelineHint') }}</p>
        </div>
        <v-btn v-if="!milestones.length && templateNodes.length" variant="tonal" color="primary" :loading="applyingTemplate" @click="applyTemplate">
          {{ $t('progress.useTemplate') }}
        </v-btn>
      </div>

      <div v-if="milestones.length" class="milestone-list">
        <article v-for="(milestone, index) in milestones" :key="milestone.id" class="milestone-row" :class="{ 'milestone-row--overdue': isOverdue(milestone) }">
          <button class="status-toggle" type="button" :aria-label="$t('progress.changeStatus')" @click="cycleStatus(milestone)">
            <v-icon :icon="statusIcon(milestone.status)" :color="statusColor(milestone.status)" size="24" />
          </button>
          <div class="timeline-rail" :class="{ 'timeline-rail--last': index === milestones.length - 1 }" />
          <button class="milestone-copy" type="button" @click="openEdit(milestone)">
            <span class="milestone-name">{{ milestone.title }}</span>
            <span class="milestone-meta">
              <span><v-icon icon="mdi-calendar-outline" size="14" />{{ milestone.deadline ? formatDate(milestone.deadline) : $t('progress.noDeadline') }}</span>
              <span :class="`priority-${milestone.priority}`"><v-icon icon="mdi-flag-outline" size="14" />{{ priorityLabel(milestone.priority) }}</span>
              <span v-if="isOverdue(milestone)" class="overdue-label">{{ $t('progress.overdue') }}</span>
            </span>
          </button>
          <v-chip size="small" variant="tonal" :color="statusColor(milestone.status)">{{ statusLabel(milestone.status) }}</v-chip>
          <v-btn icon="mdi-pencil-outline" variant="text" size="small" :aria-label="$t('common.edit')" @click="openEdit(milestone)" />
          <v-btn icon="mdi-delete-outline" variant="text" color="error" size="small" :aria-label="$t('common.delete')" @click="requestDeleteMilestone(milestone)" />
        </article>
      </div>

      <div v-else class="empty-timeline">
        <span class="empty-icon"><v-icon icon="mdi-timeline-plus-outline" size="38" /></span>
        <h3>{{ $t('progress.emptyTimelineTitle') }}</h3>
        <p>{{ $t('progress.emptyTimelineDesc') }}</p>
        <div>
          <v-btn v-if="templateNodes.length" color="primary" variant="tonal" :loading="applyingTemplate" @click="applyTemplate">{{ $t('progress.useTemplate') }}</v-btn>
          <v-btn color="primary" variant="flat" @click="openAdd">{{ $t('progress.addMilestone') }}</v-btn>
        </div>
      </div>
    </v-card>

    <v-dialog v-model="milestoneDialog" max-width="500">
      <v-card rounded="xl">
        <v-card-title class="dialog-title">{{ editingMilestone ? $t('progress.editMilestone') : $t('progress.addMilestone') }}</v-card-title>
        <v-card-text class="dialog-body">
          <v-text-field v-model="milestoneForm.name" :label="$t('progress.milestoneName')" variant="outlined" autofocus />
          <v-text-field v-model="milestoneForm.notice_time" :label="$t('progress.deadline')" type="date" variant="outlined" />
          <div class="dialog-grid">
            <v-select v-model="milestoneForm.level" :label="$t('progress.importance')" :items="priorityOptions" item-title="title" item-value="value" variant="outlined" />
            <v-select v-model="milestoneForm.status" :label="$t('progress.status')" :items="statusOptions" item-title="title" item-value="value" variant="outlined" />
          </div>
        </v-card-text>
        <v-card-actions class="dialog-actions">
          <v-spacer />
          <v-btn variant="text" @click="milestoneDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="primary" variant="flat" :loading="saving" :disabled="!milestoneForm.name.trim()" @click="saveMilestone">{{ $t('common.save') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="timelineDialog" max-width="500">
      <v-card rounded="xl">
        <v-card-title class="dialog-title">{{ $t('progress.editTimeline') }}</v-card-title>
        <v-card-text class="dialog-body">
          <v-text-field v-model="timelineForm.title" :label="$t('progress.timelineName')" variant="outlined" />
          <v-text-field v-model="timelineForm.subject" :label="$t('progress.subjectOrGroup')" variant="outlined" />
          <v-text-field v-model="timelineForm.deadline" :label="$t('progress.finalDeadline')" type="date" variant="outlined" />
          <v-select v-model="timelineForm.priority" :label="$t('progress.importance')" :items="priorityOptions" item-title="title" item-value="value" variant="outlined" />
          <v-btn color="error" variant="text" prepend-icon="mdi-delete-outline" class="px-0" @click="deleteTimelineDialog = true">{{ $t('progress.deleteTimeline') }}</v-btn>
        </v-card-text>
        <v-card-actions class="dialog-actions">
          <v-spacer />
          <v-btn variant="text" @click="timelineDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="primary" variant="flat" :loading="saving" :disabled="!timelineForm.title.trim()" @click="saveTimeline">{{ $t('common.save') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="deleteMilestoneDialog" max-width="440">
      <v-card rounded="xl">
        <v-card-title class="dialog-title">{{ $t('progress.deleteMilestoneTitle') }}</v-card-title>
        <v-card-text>{{ $t('progress.deleteMilestoneConfirm', { name: selectedMilestone?.title }) }}</v-card-text>
        <v-card-actions class="dialog-actions">
          <v-spacer />
          <v-btn variant="text" @click="deleteMilestoneDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="error" variant="flat" :loading="saving" @click="deleteMilestone">{{ $t('common.delete') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="deleteTimelineDialog" max-width="440">
      <v-card rounded="xl">
        <v-card-title class="dialog-title">{{ $t('progress.deleteTimelineTitle') }}</v-card-title>
        <v-card-text>{{ $t('progress.deleteTimelineConfirm', { name: timeline.title }) }}</v-card-text>
        <v-card-actions class="dialog-actions">
          <v-spacer />
          <v-btn variant="text" @click="deleteTimelineDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="error" variant="flat" :loading="saving" @click="deleteTimeline">{{ $t('common.delete') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="errorVisible" color="error" timeout="3500">{{ errorMessage }}</v-snackbar>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { authFetch } from '@/stores/auth'
import { notifyTasksChanged } from '@/services/taskSync'
import { openAgent } from '@/services/agentContext'

const props = defineProps({
  timeline: { type: Object, required: true },
  categoryMeta: { type: Object, required: true },
  templateNodes: { type: Array, default: () => [] },
})

const emit = defineEmits(['back', 'changed', 'removed'])
const { t, locale } = useI18n()
const milestoneDialog = ref(false)
const timelineDialog = ref(false)
const deleteMilestoneDialog = ref(false)
const deleteTimelineDialog = ref(false)
const editingMilestone = ref(null)
const selectedMilestone = ref(null)
const saving = ref(false)
const applyingTemplate = ref(false)
const errorVisible = ref(false)
const errorMessage = ref('')

const emptyMilestone = () => ({ name: '', notice_time: '', level: 'medium', status: 'pending' })
const milestoneForm = ref(emptyMilestone())
const timelineForm = ref({ title: '', subject: '', deadline: '', priority: 'medium' })

const priorityOptions = computed(() => [
  { title: t('common.low'), value: 'low' },
  { title: t('common.medium'), value: 'medium' },
  { title: t('common.high'), value: 'high' },
  { title: t('common.urgent'), value: 'urgent' },
])

const statusOptions = computed(() => [
  { title: t('progress.pending'), value: 'pending' },
  { title: t('progress.inProgress'), value: 'in_progress' },
  { title: t('progress.done'), value: 'done' },
])

const milestones = computed(() => [...(props.timeline.subtasks || [])].sort((a, b) => {
  if (!a.deadline) return 1
  if (!b.deadline) return -1
  return a.deadline.localeCompare(b.deadline)
}))

function statusProgress(status) {
  if (status === 'done' || status === 'completed') return 100
  if (status === 'in_progress') return 50
  return 0
}

const progress = computed(() => {
  if (!milestones.value.length) return 0
  return Math.round(milestones.value.reduce((sum, item) => sum + statusProgress(item.status), 0) / milestones.value.length)
})

const doneCount = computed(() => milestones.value.filter((item) => statusProgress(item.status) === 100).length)

const nextMilestone = computed(() => milestones.value.find((item) => item.status !== 'done' && item.deadline) || null)

function nodeRisk(item) {
  if (item.status === 'done') return 0
  if (!item.deadline) return 25
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const due = new Date(`${item.deadline}T00:00:00`)
  const days = Math.round((due - today) / 86400000)
  let base = 18
  if (days < 0) base = 100
  else if (days <= 3) base = 88
  else if (days <= 7) base = 72
  else if (days <= 14) base = 52
  else if (days <= 30) base = 32
  const statusFactor = item.status === 'in_progress' ? 0.72 : 1
  const priorityFactor = { low: 0.75, medium: 0.9, high: 1.05, urgent: 1.18 }[item.priority] || 0.9
  return Math.min(100, Math.round(base * statusFactor * priorityFactor))
}

const risk = computed(() => {
  const scores = milestones.value.filter((item) => item.status !== 'done').map(nodeRisk)
  if (!scores.length) return 0
  const average = scores.reduce((sum, value) => sum + value, 0) / scores.length
  return Math.round(Math.max(...scores) * 0.6 + average * 0.4)
})

const riskLevel = computed(() => risk.value >= 70 ? 'high' : risk.value >= 40 ? 'medium' : 'low')
const riskLabel = computed(() => ({ high: t('progress.highRisk'), medium: t('progress.watchRisk'), low: t('progress.lowRisk') })[riskLevel.value])
const riskColor = computed(() => ({ high: 'error', medium: 'warning', low: 'success' })[riskLevel.value])

function formatDate(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat(locale.value, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(`${value}T00:00:00`))
}

function isOverdue(item) {
  if (!item.deadline || item.status === 'done') return false
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return new Date(`${item.deadline}T00:00:00`) < today
}

function priorityLabel(value) {
  return t(`common.${value}`)
}

function statusLabel(value) {
  return ({ pending: t('progress.pending'), todo: t('progress.pending'), in_progress: t('progress.inProgress'), done: t('progress.done') })[value] || value
}

function statusIcon(value) {
  return value === 'done' ? 'mdi-check-circle' : value === 'in_progress' ? 'mdi-progress-clock' : 'mdi-circle-outline'
}

function statusColor(value) {
  return value === 'done' ? 'success' : value === 'in_progress' ? 'primary' : 'grey'
}

function showError(error) {
  errorMessage.value = error?.message || String(error)
  errorVisible.value = true
}

async function request(path, options = {}) {
  const response = await authFetch(path, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `HTTP ${response.status}`)
  }
  return response.json().catch(() => ({}))
}

function openAdd() {
  editingMilestone.value = null
  milestoneForm.value = emptyMilestone()
  milestoneDialog.value = true
}

function openEdit(item) {
  editingMilestone.value = item
  milestoneForm.value = {
    name: item.title,
    notice_time: item.deadline || '',
    level: item.priority || 'medium',
    status: item.status === 'todo' ? 'pending' : item.status,
  }
  milestoneDialog.value = true
}

async function saveMilestone() {
  saving.value = true
  try {
    const body = {
      name: milestoneForm.value.name.trim(),
      notice_time: milestoneForm.value.notice_time || null,
      level: milestoneForm.value.level,
      status: milestoneForm.value.status,
    }
    if (editingMilestone.value) {
      await request(`/api/tasks/sub-tasks/${editingMilestone.value.id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
    } else {
      await request('/api/tasks/sub-tasks', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, task_id: props.timeline.id }),
      })
    }
    milestoneDialog.value = false
    notifyTasksChanged()
    emit('changed')
  } catch (error) {
    showError(error)
  } finally {
    saving.value = false
  }
}

async function cycleStatus(item) {
  const next = item.status === 'pending' || item.status === 'todo' ? 'in_progress' : item.status === 'in_progress' ? 'done' : 'pending'
  try {
    await request(`/api/tasks/sub-tasks/${item.id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: next }),
    })
    notifyTasksChanged()
    emit('changed')
  } catch (error) {
    showError(error)
  }
}

function requestDeleteMilestone(item) {
  selectedMilestone.value = item
  deleteMilestoneDialog.value = true
}

async function deleteMilestone() {
  if (!selectedMilestone.value) return
  saving.value = true
  try {
    await request(`/api/tasks/sub-tasks/${selectedMilestone.value.id}`, { method: 'DELETE' })
    deleteMilestoneDialog.value = false
    selectedMilestone.value = null
    notifyTasksChanged()
    emit('changed')
  } catch (error) {
    showError(error)
  } finally {
    saving.value = false
  }
}

function openTimelineEdit() {
  timelineForm.value = {
    title: props.timeline.title,
    subject: props.timeline.subject || '',
    deadline: props.timeline.deadline || '',
    priority: props.timeline.priority || 'medium',
  }
  timelineDialog.value = true
}

async function saveTimeline() {
  saving.value = true
  try {
    await request(`/api/tasks/${props.timeline.id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        title: timelineForm.value.title.trim(),
        subject: timelineForm.value.subject || null,
        deadline: timelineForm.value.deadline || null,
        priority: timelineForm.value.priority,
      }),
    })
    timelineDialog.value = false
    notifyTasksChanged()
    emit('changed')
  } catch (error) {
    showError(error)
  } finally {
    saving.value = false
  }
}

async function deleteTimeline() {
  saving.value = true
  try {
    await request(`/api/tasks/${props.timeline.id}`, { method: 'DELETE' })
    deleteTimelineDialog.value = false
    timelineDialog.value = false
    notifyTasksChanged()
    emit('removed')
  } catch (error) {
    showError(error)
  } finally {
    saving.value = false
  }
}

function templateDate(index, total) {
  if (!props.timeline.deadline) return null
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  const end = new Date(`${props.timeline.deadline}T00:00:00`)
  const span = Math.max(0, end - start)
  const date = new Date(start.getTime() + span * ((index + 1) / total))
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

async function applyTemplate() {
  applyingTemplate.value = true
  try {
    for (let index = 0; index < props.templateNodes.length; index += 1) {
      await request('/api/tasks/sub-tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: props.timeline.id,
          name: props.templateNodes[index],
          notice_time: templateDate(index, props.templateNodes.length),
          level: index === props.templateNodes.length - 1 ? 'high' : 'medium',
          status: 'pending',
        }),
      })
    }
    notifyTasksChanged()
    emit('changed')
  } catch (error) {
    showError(error)
  } finally {
    applyingTemplate.value = false
  }
}

function askAgent() {
  openAgent({ category: props.timeline.category || props.categoryMeta.key, taskId: props.timeline.id, subject: props.timeline.subject, title: props.timeline.title })
}
</script>

<style scoped>
.timeline-manager { color: #1e2942; }
.timeline-header { display: flex; align-items: center; gap: 16px; margin-bottom: 24px; }
.timeline-icon { min-width: 58px; height: 50px; display: grid; place-items: center; padding: 0 12px; border-radius: 15px; font-weight: 850; }
.timeline-title { flex: 1; min-width: 0; }
.timeline-title h1 { margin-top: 2px; overflow: hidden; text-overflow: ellipsis; font-size: clamp(25px, 3vw, 36px); letter-spacing: -.035em; white-space: nowrap; }
.timeline-title p { margin-top: 4px; color: #8993a6; font-size: 12px; }
.eyebrow { color: #4a6ce2; font-size: 10px; font-weight: 800; letter-spacing: .15em; }
.timeline-actions { display: flex; align-items: center; gap: 8px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.summary-grid .v-card { min-width: 0; padding: 18px; border: 1px solid rgba(39,53,83,.09); background: rgba(255,255,255,.94) !important; }
.summary-grid span, .summary-grid strong, .summary-grid small { display: block; }
.summary-grid > .v-card > span { color: #8892a5; font-size: 10px; }
.summary-grid strong { margin: 7px 0 10px; font-size: 22px; }
.summary-grid small { overflow: hidden; color: #939cad; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.summary-grid .next-date { font-size: 15px; }
.risk-high { color: #d83d55; }.risk-medium { color: #d88924; }.risk-low { color: #249667; }
.calendar-sync-note { display: flex; align-items: center; justify-content: flex-end; gap: 6px; margin: 12px 4px; color: #738099; font-size: 10px; }
.milestone-card { overflow: hidden; border: 1px solid rgba(39,53,83,.09); background: rgba(255,255,255,.96) !important; }
.milestone-card__header { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 20px 24px; border-bottom: 1px solid #edf0f5; }
.milestone-card__header h2 { font-size: 17px; }.milestone-card__header p { margin-top: 3px; color: #929bad; font-size: 10px; }
.milestone-list { padding: 6px 0; }
.milestone-row { position: relative; display: grid; grid-template-columns: 36px minmax(0, 1fr) auto auto auto; align-items: center; gap: 12px; min-height: 78px; padding: 10px 20px; }
.milestone-row:hover { background: #fafbfe; }
.milestone-row--overdue { background: rgba(223,75,93,.035); }
.status-toggle { position: relative; z-index: 2; width: 34px; height: 34px; padding: 0; border: 0; background: transparent; cursor: pointer; }
.timeline-rail { position: absolute; z-index: 1; left: 36px; top: 50px; bottom: -28px; width: 2px; background: #e6eaf1; }.timeline-rail--last { display: none; }
.milestone-copy { min-width: 0; padding: 5px 0; border: 0; color: inherit; background: transparent; cursor: pointer; text-align: left; }
.milestone-name { display: block; overflow: hidden; font-size: 13px; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.milestone-meta { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 7px; color: #8d97a9; font-size: 9px; }
.milestone-meta > span { display: inline-flex; align-items: center; gap: 4px; }
.priority-high, .priority-urgent { color: #ce604b; }.overdue-label { color: #d83d55; font-weight: 750; }
.empty-timeline { min-height: 330px; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 35px; color: #7f899c; text-align: center; }
.empty-icon { width: 72px; height: 72px; display: grid; place-items: center; border-radius: 22px; color: #5271dc; background: #edf2ff; }
.empty-timeline h3 { margin-top: 16px; color: #334059; font-size: 17px; }.empty-timeline p { max-width: 390px; margin-top: 6px; font-size: 11px; }
.empty-timeline > div { display: flex; gap: 9px; margin-top: 18px; }
.dialog-title { padding: 22px 24px 8px; font-weight: 750; }.dialog-body { padding: 18px 24px 4px !important; }.dialog-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }.dialog-actions { padding: 12px 24px 22px; }
@media (max-width: 900px) { .summary-grid { grid-template-columns: 1fr 1fr; }.timeline-header { align-items: flex-start; flex-wrap: wrap; }.timeline-actions { width: 100%; justify-content: flex-end; }.milestone-row { grid-template-columns: 36px minmax(0, 1fr) auto; }.milestone-row > .v-btn { display: none; } }
@media (max-width: 560px) { .summary-grid { grid-template-columns: 1fr; }.timeline-title h1 { white-space: normal; }.timeline-actions { justify-content: stretch; }.timeline-actions .v-btn { flex: 1; }.timeline-actions .v-btn:nth-child(2) { flex: 0 0 auto; }.milestone-row { padding: 10px 12px; }.timeline-rail { left: 28px; }.dialog-grid { grid-template-columns: 1fr; } }
</style>
