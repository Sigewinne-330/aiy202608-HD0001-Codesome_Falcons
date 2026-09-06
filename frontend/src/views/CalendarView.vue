<template>
  <section class="calendar-workspace">
    <header class="calendar-heading">
      <div>
        <div class="eyebrow">{{ $t('calendar.eyebrow') }}</div>
        <h1>{{ $t('calendar.title') }}</h1>
        <p>{{ $t('calendar.subtitle') }}</p>
      </div>
      <div class="calendar-heading__stats">
        <div><strong>{{ monthItemCount }}</strong><span>{{ $t('calendar.monthItems') }}</span></div>
        <div><strong>{{ urgentCount }}</strong><span>{{ $t('calendar.highPriority') }}</span></div>
      </div>
    </header>

    <v-card class="calendar-card" elevation="0" rounded="xl">
      <div class="calendar-toolbar">
        <div class="month-navigation">
          <v-btn icon="mdi-chevron-left" variant="text" size="small" :aria-label="$t('calendar.prevMonth')" @click="changeMonth(-1)" />
          <div class="month-title">{{ $t('common.yearMonth', { year: currentYear, month: currentMonth }) }}</div>
          <v-btn icon="mdi-chevron-right" variant="text" size="small" :aria-label="$t('calendar.nextMonth')" @click="changeMonth(1)" />
        </div>
        <div class="calendar-legend">
          <span><i class="legend-todo" />{{ $t('calendar.legendTodo') }}</span>
          <span><i class="legend-process" />{{ $t('calendar.legendProcess') }}</span>
          <span><i class="legend-personal" />{{ $t('calendar.legendPersonal') }}</span>
          <span><i class="legend-deadline" />{{ $t('calendar.legendDeadline') }}</span>
          <span><i class="legend-urgent" />{{ $t('calendar.legendUrgent') }}</span>
          <v-btn variant="outlined" size="small" prepend-icon="mdi-calendar-today-outline" @click="goToday">{{ $t('calendar.today') }}</v-btn>
        </div>
      </div>

      <div class="weekday-grid">
        <div v-for="day in weekDayKeys" :key="day">{{ $t(`calendar.${day}`) }}</div>
      </div>

      <div class="month-grid" :class="{ 'month-grid--loading': loading }">
        <article
          v-for="day in calendarDays"
          :key="day.date"
          class="calendar-day"
          :tabindex="loading ? -1 : 0"
          :aria-label="$t('calendar.addTodoOnDate', { date: day.date })"
          :class="{
            'calendar-day--muted': !day.currentMonth,
            'calendar-day--today': day.today,
            'calendar-day--weekend': day.weekend,
          }"
          @click="handleDayCellClick(day, $event)"
          @keydown.enter.self="openTodoForDay(day)"
          @keydown.space.prevent.self="openTodoForDay(day)"
        >
          <div class="calendar-day__top">
            <span class="calendar-day__number">{{ day.number }}</span>
            <span v-if="day.today" class="today-label">{{ $t('calendar.todayLabel') }}</span>
            <span v-else-if="day.items.length" class="item-count">{{ day.items.length }}</span>
          </div>

          <div class="calendar-day__items">
            <button
              v-for="item in day.items.slice(0, 3)"
              :key="`${item.type}-${item.id}-${item.deadline_kind || 'main'}`"
              type="button"
              class="schedule-pill"
              :class="[`schedule-pill--${pillShape(item)}`, { 'schedule-pill--urgent': item.priority === 'urgent' }]"
              :style="{ '--pill-bg': pillColor(item).bg, '--pill-dot': pillColor(item).dot, '--pill-text': pillColor(item).text }"
              :title="item.deadline_kind === 'personal' ? `${item.title} (${$t('calendar.personalDeadline')})` : item.title"
              @click.stop="openItem(item)"
            >
              <i />
              <span>{{ item.title }}</span>
            </button>
            <button
              v-if="day.items.length > 3"
              type="button"
              class="more-items"
              @click.stop="openDay(day)"
            >
              {{ $t('calendar.moreItems', { n: day.items.length - 3 }) }}
            </button>
          </div>
          <span class="calendar-day__add-hint" aria-hidden="true">
            <v-icon icon="mdi-plus" size="13" />
            {{ $t('calendar.addTodoHint') }}
          </span>
        </article>

        <div v-if="loading" class="calendar-loading">
          <v-progress-circular indeterminate color="primary" size="38" />
          <span>{{ $t('calendar.syncing') }}</span>
        </div>
      </div>
    </v-card>

    <!-- 单日详情弹窗：展示当天全部日程（"+N 更多"入口），点击条目跳转逻辑与月历一致 -->
    <v-dialog v-model="dayDialog" max-width="440" scrollable>
      <v-card rounded="xl">
        <v-card-title class="day-dialog__title">
          <span>{{ $t('calendar.dayDialogTitle', { month: dialogMonth, day: dialogDay }) }}</span>
          <span class="day-dialog__count">{{ $t('calendar.dayDialogCount', { n: dialogItems.length }) }}</span>
          <v-spacer />
          <v-btn icon="mdi-close" variant="text" size="small" :aria-label="$t('common.close')" @click="dayDialog = false" />
        </v-card-title>
        <v-card-text class="day-dialog__body">
          <button
            v-for="item in dialogItems"
            :key="`${item.type}-${item.id}-${item.deadline_kind || 'main'}`"
            type="button"
            class="schedule-pill"
            :class="[`schedule-pill--${pillShape(item)}`, { 'schedule-pill--urgent': item.priority === 'urgent' }]"
            :style="{ '--pill-bg': pillColor(item).bg, '--pill-dot': pillColor(item).dot, '--pill-text': pillColor(item).text }"
            :title="item.deadline_kind === 'personal' ? `${item.title} (${$t('calendar.personalDeadline')})` : item.title"
            @click="openDialogItem(item)"
          >
            <i />
            <span>{{ item.title }}</span>
          </button>
        </v-card-text>
      </v-card>
    </v-dialog>

    <v-dialog v-model="createTodoDialog" max-width="580">
      <v-card rounded="xl">
        <v-card-title class="pt-5 px-6">{{ $t('calendar.newTodoTitle') }}</v-card-title>
        <v-card-text class="pt-4">
          <div class="calendar-todo-context">
            <v-icon icon="mdi-checkbox-marked-circle-outline" color="primary" size="24" />
            <div>
              <strong>{{ $t('tasks.todoType') }}</strong>
              <span>{{ selectedTodoDateLabel }}</span>
            </div>
          </div>

          <v-text-field v-model="todoForm.title" :label="$t('tasks.taskName')" variant="outlined" density="comfortable" class="mb-2" autofocus />
          <v-textarea v-model="todoForm.description" :label="$t('tasks.description')" variant="outlined" density="comfortable" rows="2" class="mb-2" />
          <v-text-field v-model="todoForm.subject" :label="$t('tasks.subject')" variant="outlined" density="comfortable" class="mb-2" />
          <v-row dense>
            <v-col cols="12" sm="6">
              <v-select
                v-model="todoForm.priority"
                :label="$t('tasks.priority')"
                :items="priorityOptions"
                :item-title="priorityTitle"
                item-value="value"
                variant="outlined"
                density="comfortable"
              />
            </v-col>
            <v-col cols="12" sm="6">
              <v-text-field v-model="todoForm.deadline" :label="$t('tasks.deadline')" type="date" variant="outlined" density="comfortable" />
            </v-col>
          </v-row>
          <v-row dense>
            <v-col cols="12" sm="6">
              <v-text-field
                v-model="todoForm.deadline_time"
                :label="$t('tasks.deadlineTime')"
                type="time"
                variant="outlined"
                density="comfortable"
                :disabled="!todoForm.deadline"
                :hint="$t('tasks.deadlineTimeHint')"
                persistent-hint
              />
            </v-col>
            <v-col cols="12" sm="6">
              <v-select
                v-model="todoForm.reminder_mode"
                :label="$t('tasks.reminderMode')"
                :items="reminderModeOptions"
                item-title="title"
                item-value="value"
                variant="outlined"
                density="comfortable"
                :disabled="!todoForm.deadline"
              />
            </v-col>
          </v-row>
          <div v-if="todoForm.deadline && todoForm.reminder_mode === 'custom'" class="reminder-offsets-box">
            <ReminderOffsetsEditor v-model="todoForm.reminder_offsets" />
          </div>
          <v-text-field v-model="todoForm.estimated_hours" :label="$t('tasks.estimatedHours')" type="number" min="0" variant="outlined" density="comfortable" />
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" @click="createTodoDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="primary" :loading="savingTodo" :disabled="!canCreateTodo" @click="createTodo">{{ $t('common.create') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="todoErrorVisible" color="error" timeout="3500">{{ todoErrorMessage }}</v-snackbar>
    <v-snackbar v-model="todoSuccessVisible" color="success" timeout="2500">{{ $t('calendar.todoCreated') }}</v-snackbar>
  </section>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { authFetch, useAuth } from '@/stores/auth'
import { notifyTasksChanged, onTasksChanged } from '@/services/taskSync'
import ReminderOffsetsEditor from '@/components/ReminderOffsetsEditor.vue'
import {
  buildCalendarTodoPayload,
  createCalendarTodoForm,
  isCalendarCellBlankClick,
} from '@/services/calendarTodo'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const { token } = useAuth()
const now = new Date()

const currentYear = ref(Number(route.query.year) || now.getFullYear())
const currentMonth = ref(Number(route.query.month) || now.getMonth() + 1)
const monthData = ref({})
const loading = ref(false)
// 单日详情弹窗：选中天的完整 items 列表
const dayDialog = ref(false)
const selectedDay = ref(null)
const createTodoDialog = ref(false)
const savingTodo = ref(false)
const todoErrorVisible = ref(false)
const todoErrorMessage = ref('')
const todoSuccessVisible = ref(false)
const todoForm = ref(createCalendarTodoForm(dateKey(now)))
const weekDayKeys = ['weekMon', 'weekTue', 'weekWed', 'weekThu', 'weekFri', 'weekSat', 'weekSun']

const dialogItems = computed(() => selectedDay.value?.items || [])
const dialogMonth = computed(() => (selectedDay.value ? Number(selectedDay.value.date.slice(5, 7)) : ''))
const dialogDay = computed(() => (selectedDay.value ? Number(selectedDay.value.date.slice(8, 10)) : ''))
const canCreateTodo = computed(() => Boolean(todoForm.value.title.trim() && todoForm.value.deadline))
const selectedTodoDateLabel = computed(() => {
  if (!todoForm.value.deadline) return ''
  const date = new Date(`${todoForm.value.deadline}T00:00:00`)
  if (Number.isNaN(date.getTime())) return todoForm.value.deadline
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'full' }).format(date)
})

const priorityOptions = [
  { titleKey: 'common.low', value: 'low' },
  { titleKey: 'common.medium', value: 'medium' },
  { titleKey: 'common.high', value: 'high' },
  { titleKey: 'common.urgent', value: 'urgent' },
]

const reminderModeOptions = computed(() => [
  { title: t('tasks.reminderInherit'), value: 'inherit' },
  { title: t('tasks.reminderCustom'), value: 'custom' },
  { title: t('tasks.reminderOff'), value: 'off' },
])

const monthItemCount = computed(() => Object.entries(monthData.value)
  .filter(([date]) => Number(date.slice(5, 7)) === currentMonth.value)
  .reduce((total, [, data]) => total + (data.count || 0), 0))

const urgentCount = computed(() => Object.values(monthData.value)
  .flatMap((data) => [...(data.tasks || []), ...(data.deadlines || [])])
  .filter((item) => ['urgent', 'high'].includes(item.priority)).length)

const calendarDays = computed(() => {
  const first = new Date(currentYear.value, currentMonth.value - 1, 1)
  const firstMondayOffset = (first.getDay() + 6) % 7
  const start = new Date(currentYear.value, currentMonth.value - 1, 1 - firstMondayOffset)
  const todayKey = dateKey(now)

  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start)
    date.setDate(start.getDate() + index)
    const key = dateKey(date)
    const data = monthData.value[key] || { tasks: [], deadlines: [] }
    const items = [...(data.tasks || []), ...(data.deadlines || [])]
      .sort((a, b) => priorityWeight(b.priority) - priorityWeight(a.priority))
    return {
      date: key,
      number: date.getDate(),
      currentMonth: date.getMonth() + 1 === currentMonth.value,
      today: key === todayKey,
      weekend: [0, 6].includes(date.getDay()),
      items,
    }
  })
})

function dateKey(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function priorityWeight(priority) {
  return { urgent: 4, high: 3, medium: 2, low: 1 }[priority] || 0
}

function priorityTitle(item) {
  return item.titleKey ? t(item.titleKey) : item.title
}

// Process 任务调色板（按 parent_task_id 分组循环）
const PROCESS_PALETTE = [
  { bg: '#e8f5e9', dot: '#43a047', text: '#2e5a30' },
  { bg: '#f3e5f5', dot: '#8e24aa', text: '#5c2d6e' },
  { bg: '#fff3e0', dot: '#fb8c00', text: '#6b3a00' },
  { bg: '#fce4ec', dot: '#e91e63', text: '#6e1b3a' },
  { bg: '#e0f2f1', dot: '#00897b', text: '#004d40' },
  { bg: '#ede7f6', dot: '#5e35b1', text: '#311b6e' },
  { bg: '#fff8e1', dot: '#f9a825', text: '#5c4a00' },
  { bg: '#e3f2fd', dot: '#1565c0', text: '#0d3b66' },
]

function pillColor(item) {
  if (item.type === 'deadline') return { bg: '#fff5e9', dot: '#ee8b36', text: '#84501e' }
  if (item.type === 'subtask' || item.task_type === 'process') {
    const groupId = item.type === 'subtask' ? item.parent_task_id : item.id
    return PROCESS_PALETTE[groupId % PROCESS_PALETTE.length]
  }
  return { bg: '#f0f3ff', dot: '#4e70e6', text: '#3b4a67' }
}

function pillShape(item) {
  if (item.type === 'deadline') return 'deadline'
  if (item.type === 'subtask') return 'subtask'
  if (item.deadline_kind === 'personal') {
    return item.task_type === 'process' ? 'personal-process' : 'personal-todo'
  }
  if (item.task_type === 'process') return 'process'
  return 'todo'
}

function authHeaders() {
  return token.value ? { Authorization: `Bearer ${token.value}` } : {}
}

async function loadCalendar() {
  loading.value = true
  try {
    const response = await fetch(`/api/calendar?year=${currentYear.value}&month=${currentMonth.value}`, {
      headers: authHeaders(),
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data = await response.json()
    monthData.value = Object.fromEntries((data.days || []).map((day) => [day.date, day]))
    const totalCount = Object.values(monthData.value).reduce((sum, d) => sum + (d.count || 0), 0)
    console.log(`[Calendar] Loaded ${Object.keys(monthData.value).length} days, ${totalCount} items for ${currentYear.value}-${currentMonth.value}`)
  } catch (err) {
    console.error('[Calendar] Failed to load calendar data:', err)
    monthData.value = {}
  } finally {
    loading.value = false
  }
}

async function changeMonth(offset) {
  const date = new Date(currentYear.value, currentMonth.value - 1 + offset, 1)
  currentYear.value = date.getFullYear()
  currentMonth.value = date.getMonth() + 1
  await syncRouteAndLoad()
}

async function goToday() {
  currentYear.value = now.getFullYear()
  currentMonth.value = now.getMonth() + 1
  await syncRouteAndLoad()
}

async function syncRouteAndLoad() {
  await router.replace({ query: { ...route.query, year: currentYear.value, month: currentMonth.value } })
  await loadCalendar()
}

function openItem(item) {
  if (item.type === 'deadline') {
    router.push({ path: '/deadlines', query: { focus: item.id } })
    return
  }
  if (item.type === 'subtask' && item.parent_task_id && item.category) {
    router.push({ path: `/progress/${item.category.toLowerCase()}/${item.parent_task_id}`, query: { focus: item.id } })
    return
  }
  // process 父任务（含官方/个人截止）也跳转到进度页，与子任务保持关联
  if (item.type === 'task' && item.task_type === 'process' && item.category) {
    router.push({ path: `/progress/${item.category.toLowerCase()}/${item.id}` })
    return
  }
  router.push({ path: '/tasks', query: { focus: item.id } })
}

function openDay(day) {
  selectedDay.value = day
  dayDialog.value = true
}

function handleDayCellClick(day, event) {
  if (loading.value || !isCalendarCellBlankClick(event.target)) return
  openTodoForDay(day)
}

function openTodoForDay(day) {
  if (loading.value) return
  todoForm.value = createCalendarTodoForm(day.date)
  todoErrorVisible.value = false
  createTodoDialog.value = true
}

async function createTodo() {
  if (!canCreateTodo.value) return
  savingTodo.value = true
  try {
    const payload = buildCalendarTodoPayload(todoForm.value)
    const response = await authFetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || `HTTP ${response.status}`)
    }

    const createdDate = String(payload.deadline).slice(0, 10)
    const [year, month] = createdDate.split('-').map(Number)
    createTodoDialog.value = false
    todoSuccessVisible.value = true
    if (year && month && (year !== currentYear.value || month !== currentMonth.value)) {
      currentYear.value = year
      currentMonth.value = month
      await router.replace({ query: { ...route.query, year, month } })
    }
    notifyTasksChanged()
  } catch (error) {
    todoErrorMessage.value = t('tasks.createFail', { msg: error.message })
    todoErrorVisible.value = true
  } finally {
    savingTodo.value = false
  }
}

// 弹窗内点击条目：先关弹窗再走与月历一致的跳转逻辑
function openDialogItem(item) {
  dayDialog.value = false
  openItem(item)
}

let stopTaskSync

onMounted(() => {
  loadCalendar()
  stopTaskSync = onTasksChanged(loadCalendar)
})

onBeforeUnmount(() => stopTaskSync?.())
</script>

<style scoped>
.calendar-workspace { min-height: calc(100vh - 64px); padding: 30px clamp(22px, 4vw, 58px) 38px; color: #1d2942; }
.calendar-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 22px; }
.eyebrow { margin-bottom: 4px; color: #496be1; font-size: 10px; font-weight: 800; letter-spacing: .16em; }
.calendar-heading h1 { font-size: clamp(27px, 3vw, 38px); line-height: 1.1; letter-spacing: -.04em; }
.calendar-heading p { margin-top: 8px; color: #7e899f; font-size: 13px; }
.calendar-heading__stats { display: flex; gap: 10px; }
.calendar-heading__stats > div { min-width: 106px; padding: 12px 16px; border-radius: 15px; background: rgba(255,255,255,.76); border: 1px solid rgba(29,41,66,.07); }
.calendar-heading__stats strong, .calendar-heading__stats span { display: block; }
.calendar-heading__stats strong { font-size: 20px; }
.calendar-heading__stats span { margin-top: 2px; color: #8993a6; font-size: 10px; }
.calendar-card { overflow: hidden; border: 1px solid rgba(28, 42, 71, .09); background: rgba(255,255,255,.92) !important; box-shadow: 0 18px 55px rgba(35,48,79,.08) !important; }
.calendar-toolbar { min-height: 70px; display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 14px 18px; border-bottom: 1px solid #edf0f5; }
.month-navigation { display: flex; align-items: center; gap: 7px; }
.month-title { min-width: 150px; text-align: center; font-size: 17px; font-weight: 750; }
.calendar-legend { display: flex; align-items: center; gap: 16px; }
.calendar-legend > span { display: inline-flex; align-items: center; gap: 6px; color: #838da0; font-size: 11px; }
.calendar-legend i { width: 12px; height: 12px; border-radius: 3px; }
.legend-todo { background: #4e70e6; }
.legend-process { background: #43a047; }
.legend-personal { background: transparent; border: 1.5px dashed #43a047; }
.legend-urgent { background: transparent; border: 1.5px solid #df4458; }
.legend-deadline {
  width: 21px; height: 21px;
  border-radius: 50%;
  background: transparent;
  border: 1.5px solid #ee8b36;
  position: relative;
}
.legend-deadline::after {
  content: '!';
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  font-size: 13px;
  font-weight: 800;
  color: #ee8b36;
  line-height: 1;
  font-style: normal;
}
.weekday-grid, .month-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); }
.weekday-grid { border-bottom: 1px solid #edf0f5; background: #fafbfe; }
.weekday-grid > div { padding: 11px 12px; color: #929bad; text-align: center; font-size: 10px; font-weight: 750; letter-spacing: .04em; }
.month-grid { position: relative; }
.calendar-day { position: relative; min-height: clamp(112px, 14vh, 148px); padding: 10px; border-right: 1px solid #edf0f5; border-bottom: 1px solid #edf0f5; background: rgba(255,255,255,.72); cursor: pointer; transition: background .15s, box-shadow .15s; }
.calendar-day:nth-child(7n) { border-right: 0; }
.calendar-day:nth-last-child(-n+7) { border-bottom: 0; }
.calendar-day:hover { background: #fafbff; }
.calendar-day:focus { outline: none; box-shadow: inset 0 0 0 1.5px rgba(80,114,233,.55); }
.calendar-day--muted { background: #fafbfc; opacity: .55; }
.calendar-day--weekend:not(.calendar-day--muted) { background: #fdfdff; }
.calendar-day--today { background: #f5f7ff; box-shadow: inset 0 0 0 1.5px #5072e9; }
.calendar-day__top { height: 25px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.calendar-day__number { width: 26px; height: 26px; display: grid; place-items: center; border-radius: 9px; color: #46516a; font-size: 12px; font-weight: 650; }
.calendar-day--today .calendar-day__number { color: #fff; background: #4169e8; }
.today-label { color: #4169e8; font-size: 9px; font-weight: 750; }
.item-count { min-width: 18px; height: 18px; display: grid; place-items: center; padding: 0 5px; border-radius: 999px; color: #778196; background: #f0f2f7; font-size: 9px; }
.calendar-day__items { display: flex; flex-direction: column; gap: 4px; }
.calendar-day__add-hint {
  position: absolute; right: 8px; bottom: 7px; display: inline-flex; align-items: center; gap: 2px;
  color: #6f82c7; font-size: 9px; font-weight: 700; opacity: 0; pointer-events: none;
  transform: translateY(2px); transition: opacity .15s, transform .15s;
}
.calendar-day:hover > .calendar-day__add-hint,
.calendar-day:focus > .calendar-day__add-hint { opacity: 1; transform: translateY(0); }
/* --- Schedule pills --- */
.schedule-pill {
  width: 100%; display: flex; align-items: center; gap: 6px; border: 0; padding: 5px 6px;
  border-radius: 7px; cursor: pointer; text-align: left; font-size: 10px;
  background: var(--pill-bg); color: var(--pill-text);
}
.schedule-pill:hover { filter: brightness(.97); }
.schedule-pill i {
  width: 5px; height: 5px; flex: 0 0 5px; border-radius: 50%;
  background: var(--pill-dot);
}
.schedule-pill span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* todo 任务：无填充，左侧圆头竖线 */
.schedule-pill--todo {
  background: transparent; color: #46516a;
  border-left: none;
  padding: 5px 6px 5px 9px;
  position: relative;
}
.schedule-pill--todo:hover { background: #f8f9fb; }
.schedule-pill--todo i { display: none; }
.schedule-pill--todo::before {
  content: '';
  position: absolute;
  left: 0;
  top: 4px;
  bottom: 4px;
  width: 3px;
  border-radius: 2px;
  background: var(--pill-dot);
}

/* process 父任务：圆框 + 感叹号 */
.schedule-pill--process i {
  width: 12px; height: 12px; flex: 0 0 12px;
  border-radius: 50%;
  background: transparent;
  border: 1.5px solid var(--pill-dot);
  position: relative;
  transform: none;
}
.schedule-pill--process i::after {
  content: '!';
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  font-size: 7px;
  font-weight: 800;
  color: var(--pill-dot);
  line-height: 1;
  font-style: normal;
}

/* process 个人截止：虚线圆框 + 感叹号，保持同组色 */
.schedule-pill--personal-process {
  background: transparent;
  color: var(--pill-text);
  border: 1.5px dashed var(--pill-dot);
  padding: 3.5px 4.5px; /* 补偿 border 高度，与普通 pill 对齐 */
}
.schedule-pill--personal-process:hover { background: color-mix(in srgb, var(--pill-dot) 6%, transparent); }
.schedule-pill--personal-process i {
  width: 12px; height: 12px; flex: 0 0 12px;
  border-radius: 50%;
  background: transparent;
  border: 1.5px dashed var(--pill-dot);
  position: relative;
  transform: none;
}
.schedule-pill--personal-process i::after {
  content: '!';
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  font-size: 7px;
  font-weight: 800;
  color: var(--pill-dot);
  line-height: 1;
  font-style: normal;
}

/* todo 个人截止：虚线圆头竖线 */
.schedule-pill--personal-todo {
  background: transparent; color: #46516a;
  border-left: none;
  padding: 5px 6px 5px 9px;
  position: relative;
}
.schedule-pill--personal-todo:hover { background: #f8f9fb; }
.schedule-pill--personal-todo i { display: none; }
.schedule-pill--personal-todo::before {
  content: '';
  position: absolute;
  left: 0;
  top: 4px;
  bottom: 4px;
  width: 3px;
  border-radius: 2px;
  background: repeating-linear-gradient(
    to bottom,
    var(--pill-dot) 0px,
    var(--pill-dot) 3px,
    transparent 3px,
    transparent 6px
  );
}

/* 子任务：小三角箭头 */
.schedule-pill--subtask i {
  border-radius: 0; width: 0; height: 0;
  background: transparent !important;
  border-left: 4px solid var(--pill-dot);
  border-top: 3px solid transparent;
  border-bottom: 3px solid transparent;
}

/* deadline */
.schedule-pill--deadline i { background: var(--pill-dot); }

/* urgent：保留原色，红色描边 */
.schedule-pill--urgent {
  box-shadow: inset 0 0 0 1.5px #df4458;
  border-radius: 7px;
}
/* todo 的 urgent：竖线变红 */
.schedule-pill--urgent.schedule-pill--todo,
.schedule-pill--urgent.schedule-pill--personal-todo {
  box-shadow: none;
}
.schedule-pill--urgent.schedule-pill--todo::before {
  background: #df4458;
}
.schedule-pill--urgent.schedule-pill--personal-todo::before {
  background: repeating-linear-gradient(
    to bottom,
    #df4458 0px,
    #df4458 3px,
    transparent 3px,
    transparent 6px
  );
}
/* process 个人截止的 urgent：虚线变红 */
.schedule-pill--urgent.schedule-pill--personal-process {
  border-color: #df4458;
  box-shadow: none;
}
.more-items { border: 0; padding: 2px 5px; color: #7b86a0; background: transparent; cursor: pointer; text-align: left; font-size: 9px; font-weight: 650; }
.more-items:hover { color: #4169e8; }
/* 单日详情弹窗 */
.day-dialog__title { display: flex; align-items: center; gap: 8px; padding: 18px 20px 10px; font-size: 16px; }
.day-dialog__count { color: #8993a6; font-size: 12px; font-weight: 500; }
.day-dialog__body { display: flex; flex-direction: column; gap: 6px; padding: 4px 20px 20px; }
.day-dialog__body .schedule-pill { font-size: 12px; padding: 8px 10px; }
.calendar-todo-context { display: flex; align-items: center; gap: 11px; margin-bottom: 16px; padding: 12px 14px; border: 1px solid #e2e7f5; border-radius: 13px; background: #f6f8ff; }
.calendar-todo-context strong, .calendar-todo-context span { display: block; }
.calendar-todo-context strong { color: #34415d; font-size: 12px; }
.calendar-todo-context span { margin-top: 2px; color: #7d889e; font-size: 11px; }
.reminder-offsets-box { margin: 4px 0 16px; padding: 12px; border: 1px dashed #d5dbe7; border-radius: 10px; }
.month-grid--loading { min-height: 500px; }
.calendar-loading { position: absolute; inset: 0; z-index: 2; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: #7e889d; background: rgba(255,255,255,.78); backdrop-filter: blur(3px); font-size: 12px; }
@media (max-width: 900px) {
  .calendar-workspace { padding: 22px 16px 100px; overflow-x: auto; }
  .calendar-heading__stats { display: none; }
  .calendar-card { min-width: 760px; }
  .calendar-heading p { max-width: 520px; }
}
</style>
