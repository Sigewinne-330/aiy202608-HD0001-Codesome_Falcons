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
          <span><i class="legend-deadline" />{{ $t('calendar.legendDeadline') }}</span>
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
          :class="{
            'calendar-day--muted': !day.currentMonth,
            'calendar-day--today': day.today,
            'calendar-day--weekend': day.weekend,
          }"
        >
          <div class="calendar-day__top">
            <span class="calendar-day__number">{{ day.number }}</span>
            <span v-if="day.today" class="today-label">{{ $t('calendar.todayLabel') }}</span>
            <span v-else-if="day.items.length" class="item-count">{{ day.items.length }}</span>
          </div>

          <div class="calendar-day__items">
            <button
              v-for="item in day.items.slice(0, 3)"
              :key="`${item.type}-${item.id}`"
              type="button"
              class="schedule-pill"
              :class="[`schedule-pill--${pillShape(item)}`, { 'schedule-pill--urgent': item.priority === 'urgent' }]"
              :style="{ '--pill-bg': pillColor(item).bg, '--pill-dot': pillColor(item).dot, '--pill-text': pillColor(item).text }"
              :title="item.title"
              @click="openItem(item)"
            >
              <i />
              <span>{{ item.title }}</span>
            </button>
            <button
              v-if="day.items.length > 3"
              type="button"
              class="more-items"
              @click="openDay(day)"
            >
              {{ $t('calendar.moreItems', { n: day.items.length - 3 }) }}
            </button>
          </div>
        </article>

        <div v-if="loading" class="calendar-loading">
          <v-progress-circular indeterminate color="primary" size="38" />
          <span>{{ $t('calendar.syncing') }}</span>
        </div>
      </div>
    </v-card>

    <v-snackbar v-model="dayNotice" location="bottom" timeout="2400" color="grey-darken-4">
      {{ selectedDayText }}
    </v-snackbar>
  </section>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuth } from '@/stores/auth'
import { onTasksChanged } from '@/services/taskSync'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { token } = useAuth()
const now = new Date()

const currentYear = ref(Number(route.query.year) || now.getFullYear())
const currentMonth = ref(Number(route.query.month) || now.getMonth() + 1)
const monthData = ref({})
const loading = ref(false)
const dayNotice = ref(false)
const selectedDayText = ref('')
const weekDayKeys = ['weekMon', 'weekTue', 'weekWed', 'weekThu', 'weekFri', 'weekSat', 'weekSun']

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
  } catch {
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
  router.push({ path: '/tasks', query: { focus: item.id } })
}

function openDay(day) {
  selectedDayText.value = t('calendar.dayDetail', {
    month: Number(day.date.slice(5, 7)),
    day: Number(day.date.slice(8, 10)),
    n: day.items.length,
  })
  dayNotice.value = true
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
.calendar-legend i { width: 8px; height: 8px; border-radius: 3px; }
.legend-todo { background: #4e70e6; }
.legend-process { background: #43a047; }
.legend-deadline { background: #ee8b36; }
.weekday-grid, .month-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); }
.weekday-grid { border-bottom: 1px solid #edf0f5; background: #fafbfe; }
.weekday-grid > div { padding: 11px 12px; color: #929bad; text-align: center; font-size: 10px; font-weight: 750; letter-spacing: .04em; }
.month-grid { position: relative; }
.calendar-day { min-height: clamp(112px, 14vh, 148px); padding: 10px; border-right: 1px solid #edf0f5; border-bottom: 1px solid #edf0f5; background: rgba(255,255,255,.72); transition: background .15s; }
.calendar-day:nth-child(7n) { border-right: 0; }
.calendar-day:nth-last-child(-n+7) { border-bottom: 0; }
.calendar-day:hover { background: #fafbff; }
.calendar-day--muted { background: #fafbfc; opacity: .55; }
.calendar-day--weekend:not(.calendar-day--muted) { background: #fdfdff; }
.calendar-day--today { background: #f5f7ff; box-shadow: inset 0 0 0 1.5px #5072e9; }
.calendar-day__top { height: 25px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.calendar-day__number { width: 26px; height: 26px; display: grid; place-items: center; border-radius: 9px; color: #46516a; font-size: 12px; font-weight: 650; }
.calendar-day--today .calendar-day__number { color: #fff; background: #4169e8; }
.today-label { color: #4169e8; font-size: 9px; font-weight: 750; }
.item-count { min-width: 18px; height: 18px; display: grid; place-items: center; padding: 0 5px; border-radius: 999px; color: #778196; background: #f0f2f7; font-size: 9px; }
.calendar-day__items { display: flex; flex-direction: column; gap: 4px; }
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

/* todo 任务：无填充，左侧竖线 */
.schedule-pill--todo {
  background: transparent; color: #46516a;
  border-left: 3px solid var(--pill-dot);
  border-radius: 0;
}
.schedule-pill--todo:hover { background: #f8f9fb; }
.schedule-pill--todo i { display: none; }

/* process 父任务：菱形 */
.schedule-pill--process i {
  border-radius: 1.5px; transform: rotate(45deg); width: 5px; height: 5px;
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
.schedule-pill--urgent.schedule-pill--todo {
  border-left-color: #df4458;
  box-shadow: none;
  border-radius: 0;
}
.more-items { border: 0; padding: 2px 5px; color: #7b86a0; background: transparent; cursor: pointer; text-align: left; font-size: 9px; font-weight: 650; }
.month-grid--loading { min-height: 500px; }
.calendar-loading { position: absolute; inset: 0; z-index: 2; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: #7e889d; background: rgba(255,255,255,.78); backdrop-filter: blur(3px); font-size: 12px; }
@media (max-width: 900px) {
  .calendar-workspace { padding: 22px 16px 100px; overflow-x: auto; }
  .calendar-heading__stats { display: none; }
  .calendar-card { min-width: 760px; }
  .calendar-heading p { max-width: 520px; }
}
</style>
