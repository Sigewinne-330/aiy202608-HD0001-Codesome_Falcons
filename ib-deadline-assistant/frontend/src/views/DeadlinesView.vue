<template>
  <div>
    <div class="d-flex align-center mb-4">
      <v-icon size="28" color="primary" class="mr-2">mdi-calendar-clock-outline</v-icon>
      <div>
        <div class="text-h6 font-weight-bold">{{ $t('deadlines.title') }}</div>
        <div class="text-caption text-grey">{{ $t('deadlines.subtitle') }}</div>
      </div>
      <v-spacer />
      <v-btn color="primary" prepend-icon="mdi-plus" @click="openCreate">
        {{ $t('deadlines.add') }}
      </v-btn>
    </div>

    <!-- 碰撞警告 -->
    <v-alert
      v-if="collision?.overload"
      type="warning"
      variant="tonal"
      closable
      class="mb-4"
    >
      {{ collision.suggestion }}
    </v-alert>

    <v-row>
      <v-col cols="12" md="8">
        <v-card>
          <v-card-title class="d-flex align-center">
            {{ $t('deadlines.all') }}
            <v-spacer />
            <v-chip-group v-model="statusFilter" mandatory>
              <v-chip value="all" size="small" variant="tonal">{{ $t('common.all') }}</v-chip>
              <v-chip value="pending" size="small" variant="tonal" color="warning">{{ $t('deadlines.pending') }}</v-chip>
              <v-chip value="done" size="small" variant="tonal" color="success">{{ $t('deadlines.done') }}</v-chip>
              <v-chip value="overdue" size="small" variant="tonal" color="error">{{ $t('deadlines.overdue') }}</v-chip>
            </v-chip-group>
          </v-card-title>

          <v-list v-if="filteredDeadlines.length > 0" lines="two">
            <v-list-item
              v-for="d in filteredDeadlines"
              :key="d.id"
              :id="`deadline-item-${d.id}`"
              :value="d.id"
              :class="{ 'bg-red-lighten-5': d.status === 'overdue', 'deadline-item--focused': focusedDeadlineId === d.id }"
            >
              <template v-slot:prepend>
                <v-icon
                  :color="statusColor(d.status)"
                  @click="markDone(d)"
                  style="cursor: pointer;"
                >
                  {{ d.status === 'done' ? 'mdi-check-circle' : 'mdi-circle-outline' }}
                </v-icon>
              </template>

              <v-list-item-title class="font-weight-medium">
                {{ d.title }}
              </v-list-item-title>
              <v-list-item-subtitle>
                <span v-if="d.source" class="text-caption text-grey mr-2">📎 {{ d.source }}</span>
                <span v-if="d.subject" class="text-caption text-grey">{{ d.subject }}</span>
              </v-list-item-subtitle>

              <template v-slot:append>
                <div class="text-right">
                  <div :class="d.status === 'overdue' ? 'text-error font-weight-bold' : 'text-primary'">
                    {{ formatDate(d.due_date) }}
                  </div>
                  <v-chip size="x-small" :color="priorityColor(d.priority)" variant="tonal">
                    {{ priorityLabel(d.priority) }}
                  </v-chip>
                </div>
              </template>
            </v-list-item>
          </v-list>

          <v-card-text v-else class="text-center py-8">
            <v-icon size="48" color="grey-lighten-1">mdi-calendar-check-outline</v-icon>
            <div class="text-h6 text-grey-darken-1 mt-2">{{ $t('deadlines.empty') }}</div>
          </v-card-text>
        </v-card>
      </v-col>

      <!-- 即将到期 -->
      <v-col cols="12" md="4">
        <v-card>
          <v-card-title>{{ $t('deadlines.upcoming') }}</v-card-title>
          <v-list v-if="upcoming.length > 0" density="compact">
            <v-list-item v-for="d in upcoming" :key="d.id">
              <v-list-item-title class="text-body-2">{{ d.title }}</v-list-item-title>
              <v-list-item-subtitle class="text-caption">
                {{ $t('common.daysLater', { n: daysLeft(d.due_date) }) }} · {{ d.subject || $t('common.noSubject') }}
              </v-list-item-subtitle>
            </v-list-item>
          </v-list>
          <v-card-text v-else class="text-center text-caption text-grey py-4">
            {{ $t('deadlines.upcomingEmpty') }}
          </v-card-text>
        </v-card>

        <!-- 碰撞检查 -->
        <v-card class="mt-4">
          <v-card-title>{{ $t('deadlines.collision') }}</v-card-title>
          <v-card-text>
            <v-text-field
              v-model="checkDate"
              :label="$t('deadlines.checkDateLabel')"
              variant="outlined"
              density="compact"
              hide-details
              class="mb-2"
              @keydown.enter="checkCollision"
            />
            <v-btn block variant="tonal" color="primary" @click="checkCollision" size="small">
              {{ $t('deadlines.check') }}
            </v-btn>
            <div v-if="collision" class="mt-2">
              <div class="text-caption">
                {{ $t('deadlines.collisionResult', { date: collision.date, count: collision.count }) }}
                <v-chip v-if="collision.overload" size="x-small" color="warning" class="ml-1">{{ $t('deadlines.overload') }}</v-chip>
                <v-chip v-else size="x-small" color="success" class="ml-1">{{ $t('deadlines.reasonable') }}</v-chip>
              </div>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- 添加对话框 -->
    <v-dialog v-model="dialog" max-width="500">
      <v-card :title="$t('deadlines.dialogTitle')">
        <v-card-text>
          <v-text-field v-model="form.title" :label="$t('deadlines.titleField')" variant="outlined" density="comfortable" class="mb-2" />
          <v-text-field v-model="form.source" :label="$t('deadlines.source')" variant="outlined" density="comfortable" class="mb-2" />
          <v-text-field v-model="form.subject" :label="$t('deadlines.subject')" variant="outlined" density="comfortable" class="mb-2" />
          <v-text-field v-model="form.due_date" :label="$t('deadlines.dueDate')" variant="outlined" density="comfortable" class="mb-2" />
          <v-select v-model="form.priority" :label="$t('deadlines.priority')" :items="['low','medium','high','urgent']" variant="outlined" density="comfortable" class="mb-2" />
          <v-textarea v-model="form.description" :label="$t('deadlines.note')" variant="outlined" density="comfortable" rows="2" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="dialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="primary" @click="createDeadline" :disabled="!form.title || !form.due_date">{{ $t('common.add') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { authFetch } from '@/stores/auth'

const { t } = useI18n()
const route = useRoute()
const deadlines = ref([])
const upcoming = ref([])
const collision = ref(null)
const statusFilter = ref('all')
const checkDate = ref('')
const dialog = ref(false)
const focusedDeadlineId = ref(null)  // 从提醒弹窗跳转后要高亮的 deadline id
const form = ref({
  title: '', source: '', subject: '', due_date: '', priority: 'medium', description: '',
})

const API_BASE = '/api'

const filteredDeadlines = computed(() => {
  if (statusFilter.value === 'all') return deadlines.value
  return deadlines.value.filter(d => d.status === statusFilter.value)
})

function statusColor(s) {
  return { pending: 'warning', done: 'success', overdue: 'error' }[s] || 'grey'
}
function priorityColor(p) {
  return { low: 'grey', medium: 'primary', high: 'warning', urgent: 'error' }[p] || 'grey'
}
function priorityLabel(p) {
  const keyMap = { low: 'low', medium: 'medium', high: 'high', urgent: 'urgent' }
  return t(`common.${keyMap[p] || ''}`) || p
}
function formatDate(d) {
  if (!d) return ''
  const parts = d.split('-')
  return `${parts[1]}/${parts[2]}`
}
function daysLeft(d) {
  const now = new Date()
  const due = new Date(d)
  return Math.ceil((due - now) / (1000 * 60 * 60 * 24))
}

/** 处理提醒弹窗跳转的 focus 参数：定位并高亮对应 deadline */
function handleFocus() {
  const focusId = route.query.focus
  if (!focusId || !deadlines.value.length) return
  const target = Number(focusId)
  if (!deadlines.value.some((d) => d.id === target)) return

  focusedDeadlineId.value = target
  nextTick(() => {
    document.getElementById(`deadline-item-${target}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
  window.setTimeout(() => { focusedDeadlineId.value = null }, 2600)
}

async function loadDeadlines() {
  try {
    const [all, up] = await Promise.all([
      authFetch(`${API_BASE}/deadlines`).then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)),
      authFetch(`${API_BASE}/deadlines/upcoming?days=7`).then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)),
    ])
    deadlines.value = all
    upcoming.value = up
  } catch { /* ignore */ } finally {
    handleFocus()  // 数据就绪后定位提醒跳转的目标
  }
}

// 已在 Deadline 页时再次跳转（同路由不同 query）也能响应 focus
watch(() => route.query.focus, () => handleFocus())

function openCreate() {
  form.value = { title: '', source: '', subject: '', due_date: '', priority: 'medium', description: '' }
  dialog.value = true
}

async function createDeadline() {
  try {
    const res = await authFetch(`${API_BASE}/deadlines`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    if (res.ok) {
      dialog.value = false
      await loadDeadlines()
    }
  } catch { /* ignore */ }
}

async function markDone(d) {
  const newStatus = d.status === 'done' ? 'pending' : 'done'
  try {
    await authFetch(`${API_BASE}/deadlines/${d.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    })
    await loadDeadlines()
  } catch { /* ignore */ }
}

async function checkCollision() {
  if (!checkDate.value) return
  try {
    const res = await authFetch(`${API_BASE}/deadlines/check/collisions?date=${checkDate.value}`)
    collision.value = await res.json()
  } catch { /* ignore */ }
}

onMounted(loadDeadlines)
</script>

<style scoped>
.deadline-item--focused {
  background: #eaf0ff !important;
  border-left: 3px solid #4169e8;
  border-radius: 8px;
}
</style>
