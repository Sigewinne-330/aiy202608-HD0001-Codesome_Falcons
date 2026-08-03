<template>
  <div class="calendar-panel">
    <!-- 月份导航 -->
    <div class="calendar-header">
      <v-btn
        icon="mdi-chevron-left"
        variant="text"
        size="small"
        density="compact"
        @click="prevMonth"
      />
      <span class="text-subtitle-1 font-weight-medium">
        {{ $t('common.yearMonth', { year: currentYear, month: currentMonth }) }}
      </span>
      <v-btn
        icon="mdi-chevron-right"
        variant="text"
        size="small"
        density="compact"
        @click="nextMonth"
      />
      <v-btn
        variant="text"
        size="small"
        density="compact"
        class="ml-1"
        @click="goToday"
      >
        {{ $t('calendarPanel.today') }}
      </v-btn>
    </div>

    <!-- 星期标题 -->
    <div class="weekday-row">
      <div
        v-for="day in weekDayKeys"
        :key="day"
        class="weekday-cell text-caption text-grey"
      >
        {{ $t(`calendarPanel.${day}`) }}
      </div>
    </div>

    <!-- 日历网格 -->
    <div class="calendar-grid">
      <div
        v-for="(day, index) in calendarDays"
        :key="index"
        class="day-cell"
        :class="{
          'day-cell--other-month': !day.isCurrentMonth,
          'day-cell--today': day.isToday,
          'day-cell--selected': day.isSelected,
          'day-cell--has-items': day.totalCount > 0,
        }"
        @click="selectDate(day)"
      >
        <span class="day-number">{{ day.dayOfMonth }}</span>
        <!-- 任务/截止日期标记点 -->
        <div v-if="day.totalCount > 0" class="day-dots">
          <span
            v-for="(dot, di) in day.dots"
            :key="di"
            class="day-dot"
            :class="`day-dot--${dot}`"
          />
          <span v-if="day.totalCount > 3" class="day-more text-caption">
            +{{ day.totalCount - 3 }}
          </span>
        </div>
      </div>
    </div>

    <!-- 选中日期的任务/截止日期列表 -->
    <v-divider v-if="selectedDateStr" class="my-2" />

    <div v-if="selectedDateStr" class="day-detail">
      <div class="day-detail-header text-body-2 font-weight-medium mb-2">
        {{ formatDetailDate(selectedDateStr) }}
        <span class="text-caption text-grey ml-1">
          {{ $t('calendarPanel.detailCount', { n: selectedDayItems.length }) }}
        </span>
      </div>

      <div v-if="selectedDayItems.length === 0" class="text-caption text-grey pa-2">
        {{ $t('calendarPanel.noItems') }}
      </div>

      <div
        v-for="item in selectedDayItems"
        :key="`${item.type}-${item.id}`"
        class="day-item"
      >
        <v-icon
          :icon="item.type === 'deadline' ? 'mdi-alert-circle' : 'mdi-checkbox-blank-circle'"
          :color="item.type === 'deadline' ? 'warning' : 'primary'"
          size="14"
          class="mr-1"
        />
        <span class="text-body-2 day-item-title">{{ item.title }}</span>
        <v-chip
          :color="priorityColor(item.priority)"
          size="x-small"
          variant="tonal"
          class="ml-auto"
        >
          {{ priorityLabel(item.priority) }}
        </v-chip>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { authFetch } from '@/stores/auth'

const { t } = useI18n()
const weekDayKeys = ['week1', 'week2', 'week3', 'week4', 'week5', 'week6', 'week7']

const today = new Date()
const currentYear = ref(today.getFullYear())
const currentMonth = ref(today.getMonth() + 1)
const selectedDate = ref(null)  // 选中的日期对象
const monthData = ref([])  // 从 API 获取的当月数据

// 加载日历数据
async function loadCalendarData() {
  try {
    const resp = await authFetch(`/api/calendar?year=${currentYear.value}&month=${currentMonth.value}`)
    if (resp.ok) {
      const data = await resp.json()
      // 按日期建立索引
      const dateMap = {}
      for (const d of data.days) {
        dateMap[d.date] = d
      }
      monthData.value = dateMap
    }
  } catch (err) {
    console.error(t('calendarPanel.loadError'), err)
    monthData.value = {}
  }
}

// 构建日历网格数据
const calendarDays = computed(() => {
  const year = currentYear.value
  const month = currentMonth.value

  // 当月第一天和最后一天
  const firstDay = new Date(year, month - 1, 1)
  const lastDay = new Date(year, month, 0)
  const totalDays = lastDay.getDate()

  // 第一天是周几（0=周日，调整为 1=周一...7=周日）
  let startDayOfWeek = firstDay.getDay()
  startDayOfWeek = startDayOfWeek === 0 ? 7 : startDayOfWeek

  const days = []

  // 上月填充
  const prevMonthLastDay = new Date(year, month - 1, 0).getDate()
  for (let i = startDayOfWeek - 1; i > 0; i--) {
    const d = prevMonthLastDay - i + 1
    const dateStr = formatDateStr(year, month - 1, d)
    days.push({
      dayOfMonth: d,
      dateStr,
      isCurrentMonth: false,
      isToday: false,
      isSelected: false,
      totalCount: 0,
      dots: [],
    })
  }

  // 当月日期
  const todayStr = formatDateStr(today.getFullYear(), today.getMonth() + 1, today.getDate())
  const selectedStr = selectedDate.value ? formatDateStr(selectedDate.value.year, selectedDate.value.month, selectedDate.value.day) : null

  for (let d = 1; d <= totalDays; d++) {
    const dateStr = formatDateStr(year, month, d)
    const dayData = monthData.value[dateStr]
    const count = dayData ? dayData.count : 0
    const dots = buildDots(dayData)

    days.push({
      dayOfMonth: d,
      dateStr,
      isCurrentMonth: true,
      isToday: dateStr === todayStr,
      isSelected: dateStr === selectedStr,
      totalCount: count,
      dots,
    })
  }

  // 下月填充
  const remaining = (7 - (days.length % 7)) % 7
  for (let i = 1; i <= remaining; i++) {
    const dateStr = formatDateStr(year, month + 1, i)
    days.push({
      dayOfMonth: i,
      dateStr,
      isCurrentMonth: false,
      isToday: false,
      isSelected: false,
      totalCount: 0,
      dots: [],
    })
  }

  return days
})

// 构建标记点（最多3个，task 蓝色 + deadline 橙色）
function buildDots(dayData) {
  if (!dayData) return []
  const dots = []
  if (dayData.tasks && dayData.tasks.length > 0) {
    dots.push('task')
  }
  if (dayData.deadlines && dayData.deadlines.length > 0) {
    dots.push('deadline')
  }
  // 如果某类型超过 1 个，加一个额外标记
  if (dayData.tasks && dayData.tasks.length >= 3) {
    dots.push('task')
  }
  if (dayData.deadlines && dayData.deadlines.length >= 3) {
    dots.push('deadline')
  }
  return dots.slice(0, 3)
}

// 选中日期的详细条目
const selectedDateStr = computed(() => {
  if (!selectedDate.value) return null
  return formatDateStr(
    selectedDate.value.year,
    selectedDate.value.month,
    selectedDate.value.day
  )
})

const selectedDayItems = computed(() => {
  if (!selectedDateStr.value) return []
  const dayData = monthData.value[selectedDateStr.value]
  if (!dayData) return []
  const items = []
  for (const t of (dayData.tasks || [])) {
    items.push({ ...t, sortPriority: prioritySort(t.priority) })
  }
  for (const d of (dayData.deadlines || [])) {
    items.push({ ...d, sortPriority: prioritySort(d.priority) })
  }
  // 按优先级排序：urgent > high > medium > low
  items.sort((a, b) => b.sortPriority - a.sortPriority)
  return items
})

function prioritySort(p) {
  const map = { urgent: 4, high: 3, medium: 2, low: 1 }
  return map[p] || 0
}

function formatDateStr(year, month, day) {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function selectDate(day) {
  if (day.isCurrentMonth) {
    const [y, m, d] = day.dateStr.split('-').map(Number)
    selectedDate.value = { year: y, month: m, day: d }
  }
}

function prevMonth() {
  if (currentMonth.value === 1) {
    currentMonth.value = 12
    currentYear.value--
  } else {
    currentMonth.value--
  }
  selectedDate.value = null
  loadCalendarData()
}

function nextMonth() {
  if (currentMonth.value === 12) {
    currentMonth.value = 1
    currentYear.value++
  } else {
    currentMonth.value++
  }
  selectedDate.value = null
  loadCalendarData()
}

function goToday() {
  currentYear.value = today.getFullYear()
  currentMonth.value = today.getMonth() + 1
  selectedDate.value = {
    year: today.getFullYear(),
    month: today.getMonth() + 1,
    day: today.getDate(),
  }
  loadCalendarData()
}

function formatDetailDate(dateStr) {
  const d = new Date(dateStr)
  const weekKeyMap = { 0: 'week7', 1: 'week1', 2: 'week2', 3: 'week3', 4: 'week4', 5: 'week5', 6: 'week6' }
  return `${t('common.monthDay', { month: d.getMonth() + 1, day: d.getDate() })}${t('calendarPanel.weekPrefix')}${t(`calendarPanel.${weekKeyMap[d.getDay()]}`)}`
}

function priorityColor(p) {
  const map = { urgent: '#FF7043', high: '#EF5350', medium: '#FFA726', low: '#66BB6A' }
  return map[p] || '#9E9E9E'
}

function priorityLabel(p) {
  const keyMap = { urgent: 'urgent', high: 'high', medium: 'medium', low: 'low' }
  return t(`common.${keyMap[p] || ''}`) || p
}

onMounted(() => {
  loadCalendarData()
})
</script>

<style scoped>
.calendar-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 8px;
  overflow-y: auto;
  background: #FAFBFC;
  border-right: 1px solid #E0E0E0;
}

/* 月份导航 */
.calendar-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 4px 0 8px 0;
}

/* 星期行 */
.weekday-row {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  text-align: center;
  padding: 4px 0;
  border-bottom: 1px solid #E8E8E8;
}

.weekday-cell {
  padding: 2px 0;
  font-weight: 500;
}

/* 日历网格 */
.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
  padding-top: 4px;
}

.day-cell {
  aspect-ratio: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding: 2px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
  position: relative;
  min-height: 36px;
}

.day-cell:hover {
  background: #E3F2FD;
}

.day-cell--other-month {
  opacity: 0.35;
  pointer-events: none;
}

.day-cell--today {
  background: #E3F2FD;
  border: 1.5px solid #1565C0;
}

.day-cell--selected {
  background: #1565C0 !important;
  border-color: #1565C0;
}

.day-cell--selected .day-number {
  color: #fff !important;
  font-weight: 700;
}

.day-cell--selected .day-dot {
  border-color: #fff;
}

.day-number {
  font-size: 12px;
  color: #333;
  line-height: 1;
  margin-top: 1px;
}

/* 标记点 */
.day-dots {
  display: flex;
  gap: 2px;
  margin-top: 2px;
  flex-wrap: wrap;
  justify-content: center;
}

.day-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  display: inline-block;
}

.day-dot--task {
  background: #1565C0;
}

.day-dot--deadline {
  background: #FF7043;
}

.day-more {
  color: #999;
  font-size: 9px;
  line-height: 1;
}

/* 选中日期的详细信息 */
.day-detail {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.day-detail-header {
  padding: 4px 8px;
}

.day-item {
  display: flex;
  align-items: center;
  padding: 6px 8px;
  border-radius: 6px;
  margin-bottom: 2px;
  transition: background 0.15s;
}

.day-item:hover {
  background: #F5F5F5;
}

.day-item-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
