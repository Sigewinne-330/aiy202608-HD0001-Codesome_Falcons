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

    <v-alert v-if="loadError" type="error" variant="tonal" density="compact" class="calendar-error">
      {{ loadError }}
      <template #append><v-btn size="small" variant="text" @click="loadCalendar">{{ $t('common.retry') }}</v-btn></template>
    </v-alert>

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

      <div class="month-grid calendar-month-grid" :class="{ 'month-grid--loading': loading }">
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
              :key="`${item.type}-${item.id}-${item.deadline_kind || 'main'}`"
              type="button"
              class="schedule-pill"
              :class="[`schedule-pill--${pillShape(item)}`, { 'schedule-pill--urgent': item.priority === 'urgent' }]"
              :style="{ '--pill-bg': pillColor(item).bg, '--pill-dot': pillColor(item).dot, '--pill-text': pillColor(item).text }"
              :title="item.deadline_kind === 'personal' ? `${item.title} (${$t('calendar.personalDeadline')})` : item.title"
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
            <button
              v-if="day.currentMonth && !day.items.length"
              type="button"
              class="empty-day-action"
              :aria-label="$t('calendar.addTaskForDate', { date: day.date })"
              :title="$t('calendar.emptyDateHint')"
              @click="openCreateForDay(day.date)"
            >
              <v-icon icon="mdi-plus" size="14" />
              <span>{{ $t('calendar.addTask') }}</span>
            </button>
          </div>
        </article>

        <div v-if="loading" class="calendar-loading">
          <v-progress-circular indeterminate color="primary" size="38" />
          <span>{{ $t('calendar.syncing') }}</span>
        </div>
      </div>

      <div class="mobile-agenda" :class="{ 'mobile-agenda--loading': loading }" :aria-label="$t('calendar.mobileAgenda')">
        <article v-for="day in mobileDays" :key="`mobile-${day.date}`" class="mobile-day" :class="{ 'mobile-day--today': day.today }">
          <div class="mobile-day__date">
            <strong>{{ day.number }}</strong>
            <span>{{ $t(`calendar.${weekDayKeys[(new Date(`${day.date}T00:00:00`).getDay() + 6) % 7]}`) }}</span>
            <v-chip v-if="day.today" size="x-small" color="primary" variant="tonal">{{ $t('calendar.todayLabel') }}</v-chip>
            <small v-else-if="day.items.length">{{ $t('common.items', { n: day.items.length }) }}</small>
          </div>
          <div class="mobile-day__items">
            <button
              v-for="item in day.items"
              :key="`mobile-${item.type}-${item.id}-${item.deadline_kind || 'main'}`"
              type="button"
              class="mobile-schedule-item"
              @click="openItem(item)"
            >
              <i :style="{ background: pillColor(item).dot }" />
              <span><strong>{{ item.title }}</strong><small>{{ item.subject || $t('common.uncategorized') }}</small></span>
              <v-icon icon="mdi-chevron-right" size="16" />
            </button>
            <button type="button" class="mobile-add-task" @click="openCreateForDay(day.date)">
              <v-icon icon="mdi-plus" size="15" />{{ $t('calendar.addTask') }}
            </button>
          </div>
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
  </section>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api } from '@/stores/auth'
import { onTasksChanged } from '@/services/taskSync'
import { notify } from '@/services/feedback'
import { priorityWeight } from '@/utils/tasks'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const now = new Date()

const currentYear = ref(Number(route.query.year) || now.getFullYear())
const currentMonth = ref(Number(route.query.month) || now.getMonth() + 1)
const monthData = ref({})
const loading = ref(false)
const loadError = ref('')
// 单日详情弹窗：选中天的完整 items 列表
const dayDialog = ref(false)
const selectedDay = ref(null)
const weekDayKeys = ['weekMon', 'weekTue', 'weekWed', 'weekThu', 'weekFri', 'weekSat', 'weekSun']

const dialogItems = computed(() => selectedDay.value?.items || [])
const dialogMonth = computed(() => (selectedDay.value ? Number(selectedDay.value.date.slice(5, 7)) : ''))
const dialogDay = computed(() => (selectedDay.value ? Number(selectedDay.value.date.slice(8, 10)) : ''))

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
const mobileDays = computed(() => calendarDays.value.filter((day) => day.currentMonth))

function dateKey(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

// Process 任务调色板（按 parent_task_id 分组循环）
const PROCESS_PALETTE = [
  { bg: 'var(--ib-primary-soft)', dot: 'var(--ib-primary)', text: 'var(--ib-text)' },
  { bg: 'var(--ib-surface-subtle)', dot: 'var(--ib-primary-strong)', text: 'var(--ib-text)' },
]

function pillColor(item) {
  if (item.type === 'deadline') return { bg: 'var(--ib-surface-subtle)', dot: 'var(--ib-warning)', text: 'var(--ib-text)' }
  if (item.type === 'subtask' || item.task_type === 'process') {
    const groupId = item.type === 'subtask' ? item.parent_task_id : item.id
    return PROCESS_PALETTE[groupId % PROCESS_PALETTE.length]
  }
  return { bg: 'var(--ib-primary-soft)', dot: 'var(--ib-primary)', text: 'var(--ib-text)' }
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

async function loadCalendar() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await api(`/api/calendar?year=${currentYear.value}&month=${currentMonth.value}`)
    monthData.value = Object.fromEntries((data.days || []).map((day) => [day.date, day]))
  } catch (err) {
    monthData.value = {}
    loadError.value = err?.message || t('calendar.loadFailed')
    notify(loadError.value, { type: 'error' })
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

function openCreateForDay(date) {
  router.push({ path: '/tasks', query: { create: '1', deadline: date } })
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
.month-grid--loading { min-height: 500px; }
.calendar-loading { position: absolute; inset: 0; z-index: 2; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: #7e889d; background: rgba(255,255,255,.78); backdrop-filter: blur(3px); font-size: 12px; }
@media (max-width: 900px) {
  .calendar-workspace { padding: 22px 16px 100px; overflow-x: auto; }
  .calendar-heading__stats { display: none; }
  .calendar-card { min-width: 760px; }
  .calendar-heading p { max-width: 520px; }
}

/* Mono Workspace visual layer */
.calendar-workspace { min-height: calc(100vh - 60px); padding: 28px clamp(18px, 3vw, 44px) 72px; color: var(--ib-text); background: var(--ib-background); }
.calendar-heading { width: min(100%, var(--ib-content-max)); margin-inline: auto; }
.calendar-heading .eyebrow { color: var(--ib-primary-strong); }
.calendar-heading h1 { color: var(--ib-text); }
.calendar-heading p,
.calendar-heading__stats span,
.calendar-legend > span { color: var(--ib-text-secondary); }
.calendar-heading__stats > div,
.calendar-card { border-color: var(--ib-border); background: var(--ib-surface) !important; box-shadow: var(--ib-shadow-card) !important; }
.calendar-card { width: min(100%, var(--ib-content-max)); margin-inline: auto; border-radius: var(--ib-radius-lg) !important; }
.calendar-toolbar,
.weekday-grid,
.calendar-day { border-color: var(--ib-border); }
.weekday-grid { background: var(--ib-surface-subtle); }
.weekday-grid > div { color: var(--ib-text-muted); }
.calendar-day { background: var(--ib-surface); }
.calendar-day:hover { background: var(--ib-surface-subtle); }
.calendar-day--muted,
.calendar-day--weekend:not(.calendar-day--muted) { background: color-mix(in srgb, var(--ib-surface-subtle) 62%, var(--ib-surface)); }
.calendar-day--today { background: var(--ib-primary-soft); box-shadow: inset 0 0 0 1.5px var(--ib-primary); }
.calendar-day__number,
.schedule-pill--todo,
.schedule-pill--personal-todo { color: var(--ib-text-secondary); }
.calendar-day--today .calendar-day__number { background: var(--ib-primary); color: var(--ib-on-primary); }
.today-label,
.more-items:hover { color: var(--ib-primary-strong); }
.item-count { background: var(--ib-surface-subtle); color: var(--ib-text-secondary); }
.schedule-pill--todo:hover,
.schedule-pill--personal-todo:hover { background: var(--ib-surface-subtle); }
.calendar-loading { background: color-mix(in srgb, var(--ib-surface) 84%, transparent); color: var(--ib-text-secondary); }
:global([data-theme='dark']) .schedule-pill:not(.schedule-pill--todo):not(.schedule-pill--personal-todo) {
  background: color-mix(in srgb, var(--pill-dot) 16%, var(--ib-surface));
  color: var(--ib-text);
}
.calendar-error { width: min(100%, var(--ib-content-max)); margin: 0 auto 14px; }
.legend-todo,
.legend-process { background: var(--ib-primary); }
.legend-personal { border-color: var(--ib-primary); }
.legend-deadline { border-color: var(--ib-warning); }
.legend-deadline::after { color: var(--ib-warning); }
.legend-urgent { border-color: var(--ib-danger); }
.empty-day-action { width: 100%; min-height: 38px; display: flex; align-items: center; justify-content: center; gap: 4px; padding: 5px; border: 1px dashed transparent; border-radius: 7px; color: transparent; background: transparent; cursor: pointer; font-size: 9px; }
.calendar-day:hover .empty-day-action,
.empty-day-action:focus-visible { border-color: var(--ib-border-strong); color: var(--ib-primary-strong); background: var(--ib-surface-subtle); }
.mobile-agenda { position: relative; display: none; }
.mobile-day { display: grid; grid-template-columns: 74px minmax(0, 1fr); min-height: 76px; border-bottom: 1px solid var(--ib-border); }
.mobile-day:last-child { border-bottom: 0; }
.mobile-day--today { background: var(--ib-primary-soft); }
.mobile-day__date { display: flex; align-items: center; align-content: center; flex-wrap: wrap; gap: 4px; padding: 12px; border-right: 1px solid var(--ib-border); }
.mobile-day__date strong { color: var(--ib-text); font-size: 20px; line-height: 1; }
.mobile-day__date > span { color: var(--ib-text-secondary); font-size: 10px; }
.mobile-day__date small { width: 100%; color: var(--ib-text-muted); font-size: 9px; }
.mobile-day__items { display: grid; align-content: center; gap: 5px; padding: 9px; }
.mobile-schedule-item { width: 100%; display: grid; grid-template-columns: 5px minmax(0, 1fr) 16px; align-items: center; gap: 8px; padding: 7px 6px; border: 0; border-radius: 7px; color: var(--ib-text); background: var(--ib-surface); cursor: pointer; text-align: left; }
.mobile-schedule-item:hover { background: var(--ib-surface-subtle); }
.mobile-schedule-item > i { width: 4px; height: 28px; border-radius: 999px; }
.mobile-schedule-item > span { display: grid; min-width: 0; gap: 2px; }
.mobile-schedule-item strong { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.mobile-schedule-item small { color: var(--ib-text-muted); font-size: 9px; }
.mobile-add-task { width: 100%; display: flex; align-items: center; justify-content: center; gap: 4px; padding: 7px; border: 1px dashed var(--ib-border-strong); border-radius: 7px; color: var(--ib-primary-strong); background: transparent; cursor: pointer; font-size: 10px; }
.mobile-add-task:hover { border-color: var(--ib-primary); background: var(--ib-primary-soft); }

@media (max-width: 700px) {
  .calendar-workspace { overflow-x: visible; padding-inline: 12px; }
  .calendar-card { min-width: 0; }
  .calendar-toolbar { align-items: stretch; flex-direction: column; gap: 10px; }
  .month-navigation { justify-content: space-between; }
  .month-title { min-width: 0; }
  .calendar-legend > span { display: none; }
  .calendar-legend { justify-content: flex-end; }
  .weekday-grid,
  .calendar-month-grid { display: none; }
  .mobile-agenda { display: block; }
  .calendar-loading { min-height: 320px; }
}
</style>
