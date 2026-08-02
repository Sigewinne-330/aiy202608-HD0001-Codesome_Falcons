<template>
  <div class="calendar-page">
    <!-- 顶部工具栏 -->
    <div class="calendar-toolbar">
      <div class="toolbar-left">
        <v-btn icon variant="text" @click="prevMonth">
          <v-icon>mdi-chevron-left</v-icon>
        </v-btn>
        <h2 class="text-h5 font-weight-bold mx-3">
          {{ currentYear }}年{{ currentMonth }}月
        </h2>
        <v-btn icon variant="text" @click="nextMonth">
          <v-icon>mdi-chevron-right</v-icon>
        </v-btn>
        <v-btn variant="outlined" size="small" class="ml-3" @click="goToday">
          今天
        </v-btn>
      </div>
      <div class="toolbar-right">
        <v-chip v-if="loading" size="small" color="primary" variant="tonal">
          <v-icon size="16" class="mr-1">mdi-loading mdi-spin</v-icon>
          加载中
        </v-chip>
      </div>
    </div>

    <v-divider />

    <!-- 主内容区：左侧日历 + 右侧任务 -->
    <div class="calendar-body">
      <!-- 左侧：日历网格 -->
      <div class="calendar-main">
        <!-- 星期标题 -->
        <div class="weekday-row">
          <div
            v-for="day in weekDays"
            :key="day"
            class="weekday-cell"
          >
            {{ day }}
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
            }"
            @click="selectDate(day)"
          >
            <div class="day-top">
              <span class="day-number">{{ day.dayOfMonth }}</span>
            </div>
            <!-- 任务列表（当天日期格子内） -->
            <div class="day-items" v-if="day.totalCount > 0 && day.isCurrentMonth">
              <div
                v-for="item in day.items.slice(0, 4)"
                :key="`${item.type}-${item.id}`"
                class="day-item-mini"
                :class="`day-item-mini--${item.type}`"
                :title="item.title"
              >
                {{ item.title }}
              </div>
              <div v-if="day.totalCount > 4" class="day-more-text">
                +{{ day.totalCount - 4 }} 项更多...
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：选中日期的任务详情面板 -->
      <div class="calendar-sidebar" v-if="selectedDateStr">
        <div class="sidebar-header">
          <h3 class="text-h6 font-weight-medium">
            {{ formatDetailDate(selectedDateStr) }}
          </h3>
          <v-chip size="small" variant="tonal" color="primary">
            {{ selectedDayItems.length }} 项任务
          </v-chip>
        </div>

        <v-divider class="mb-3" />

        <div v-if="selectedDayItems.length === 0" class="empty-hint">
          <v-icon icon="mdi-coffee-outline" size="48" color="grey-lighten-1" class="mb-3" />
          <p class="text-grey">当天暂无任务或截止日期</p>
        </div>

        <div class="sidebar-list">
          <div
            v-for="item in selectedDayItems"
            :key="`${item.type}-${item.id}`"
            class="sidebar-item"
          >
            <div class="sidebar-item-left">
              <v-icon
                :icon="item.type === 'deadline' ? 'mdi-alert-circle' : 'mdi-checkbox-blank-circle'"
                :color="item.type === 'deadline' ? 'warning' : 'primary'"
                size="16"
              />
            </div>
            <div class="sidebar-item-center">
              <div class="sidebar-item-title">{{ item.title }}</div>
              <div class="sidebar-item-meta">
                <v-chip
                  :color="priorityColor(item.priority)"
                  size="x-small"
                  variant="tonal"
                  label
                >
                  {{ priorityLabel(item.priority) }}
                </v-chip>
                <span class="text-caption text-grey ml-1">{{ item.type === 'deadline' ? '截止日期' : '任务' }}</span>
              </div>
            </div>
            <div class="sidebar-item-right">
              <v-chip
                v-if="item.type === 'task'"
                :color="statusColor(item.status)"
                size="x-small"
                variant="flat"
                label
              >
                {{ statusLabel(item.status) }}
              </v-chip>
            </div>
          </div>
        </div>
      </div>

      <!-- 未选择日期时的提示 -->
      <div class="calendar-sidebar" v-else>
        <div class="empty-hint">
          <v-icon icon="mdi-gesture-tap" size="48" color="grey-lighten-1" class="mb-3" />
          <p class="text-grey mb-1">点击日历中的日期</p>
          <p class="text-caption text-grey-lighten-1">查看当天任务和截止日期</p>
        </div>

        <!-- 即将到期的任务预览 -->
        <v-divider class="my-4" />
        <div class="text-body-2 font-weight-medium mb-2">📋 即将到期</div>
        <div v-if="upcomingItems.length === 0" class="text-caption text-grey">
          暂无即将到期的任务
        </div>
        <div
          v-for="item in upcomingItems"
          :key="`up-${item.type}-${item.id}`"
          class="sidebar-item"
        >
          <div class="sidebar-item-left">
            <v-icon
              :icon="item.type === 'deadline' ? 'mdi-alert-circle' : 'mdi-checkbox-blank-circle'"
              :color="item.type === 'deadline' ? 'warning' : 'primary'"
              size="16"
            />
          </div>
          <div class="sidebar-item-center">
            <div class="sidebar-item-title">{{ item.title }}</div>
            <div class="text-caption text-grey">{{ item.dateStr }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

const weekDays = ['一', '二', '三', '四', '五', '六', '日']

const today = new Date()
const currentYear = ref(today.getFullYear())
const currentMonth = ref(today.getMonth() + 1)
const selectedDate = ref(null)
const monthData = ref({})
const loading = ref(false)

// 加载日历数据
async function loadCalendarData() {
  loading.value = true
  try {
    const resp = await fetch(`/api/calendar?year=${currentYear.value}&month=${currentMonth.value}`)
    if (resp.ok) {
      const data = await resp.json()
      const dateMap = {}
      for (const d of data.days) {
        dateMap[d.date] = d
      }
      monthData.value = dateMap
    }
  } catch (err) {
    console.error('加载日历数据失败:', err)
    monthData.value = {}
  } finally {
    loading.value = false
  }
}

// 构建日历网格
const calendarDays = computed(() => {
  const year = currentYear.value
  const month = currentMonth.value
  const firstDay = new Date(year, month - 1, 1)
  const lastDay = new Date(year, month, 0)
  const totalDays = lastDay.getDate()

  let startDayOfWeek = firstDay.getDay()
  startDayOfWeek = startDayOfWeek === 0 ? 7 : startDayOfWeek

  const days = []
  const prevMonthLastDay = new Date(year, month - 1, 0).getDate()

  // 上月填充
  for (let i = startDayOfWeek - 1; i > 0; i--) {
    const d = prevMonthLastDay - i + 1
    days.push(makeDayEntry(year, month - 1, d, false, false))
  }

  // 当月
  const todayStr = fmtDate(today.getFullYear(), today.getMonth() + 1, today.getDate())
  const selectedStr = selectedDate.value
    ? fmtDate(selectedDate.value.year, selectedDate.value.month, selectedDate.value.day)
    : null

  for (let d = 1; d <= totalDays; d++) {
    const dateStr = fmtDate(year, month, d)
    const entry = makeDayEntry(year, month, d, true, dateStr === todayStr)
    entry.isSelected = dateStr === selectedStr

    // 附加该日的任务数据
    const data = monthData.value[dateStr]
    if (data) {
      entry.totalCount = data.count
      const items = []
      for (const t of (data.tasks || [])) items.push(t)
      for (const d of (data.deadlines || [])) items.push(d)
      items.sort((a, b) => prioritySort(b.priority) - prioritySort(a.priority))
      entry.items = items
    }
    days.push(entry)
  }

  // 下月填充
  const remaining = (7 - (days.length % 7)) % 7
  for (let i = 1; i <= remaining; i++) {
    days.push(makeDayEntry(year, month + 1, i, false, false))
  }

  return days
})

function makeDayEntry(year, month, day, isCurrentMonth, isToday) {
  return {
    dayOfMonth: day,
    dateStr: fmtDate(year, month, day),
    isCurrentMonth,
    isToday,
    isSelected: false,
    totalCount: 0,
    items: [],
  }
}

function fmtDate(year, month, day) {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function selectDate(day) {
  if (day.isCurrentMonth) {
    const [y, m, d] = day.dateStr.split('-').map(Number)
    selectedDate.value = { year: y, month: m, day: d }
  }
}

// 选中日期的条目
const selectedDateStr = computed(() => {
  if (!selectedDate.value) return null
  return fmtDate(selectedDate.value.year, selectedDate.value.month, selectedDate.value.day)
})

const selectedDayItems = computed(() => {
  if (!selectedDateStr.value) return []
  const dayData = monthData.value[selectedDateStr.value]
  if (!dayData) return []
  const items = []
  for (const t of (dayData.tasks || [])) items.push(t)
  for (const d of (dayData.deadlines || [])) items.push(d)
  items.sort((a, b) => prioritySort(b.priority) - prioritySort(a.priority))
  return items
})

// 即将到期（未来7天内的所有条目，未选择日期时展示）
const upcomingItems = computed(() => {
  const todayStr = fmtDate(today.getFullYear(), today.getMonth() + 1, today.getDate())
  const endDate = new Date(today)
  endDate.setDate(endDate.getDate() + 7)
  const endStr = fmtDate(endDate.getFullYear(), endDate.getMonth() + 1, endDate.getDate())

  const items = []
  for (const [dateStr, data] of Object.entries(monthData.value)) {
    if (dateStr < todayStr || dateStr > endStr) continue
    for (const t of (data.tasks || [])) {
      items.push({ ...t, dateStr })
    }
    for (const d of (data.deadlines || [])) {
      items.push({ ...d, dateStr })
    }
  }
  items.sort((a, b) => prioritySort(b.priority) - prioritySort(a.priority))
  return items.slice(0, 10)
})

function prioritySort(p) {
  const map = { urgent: 4, high: 3, medium: 2, low: 1 }
  return map[p] || 0
}

function prevMonth() {
  if (currentMonth.value === 1) { currentMonth.value = 12; currentYear.value-- }
  else { currentMonth.value-- }
  selectedDate.value = null
  loadCalendarData()
}

function nextMonth() {
  if (currentMonth.value === 12) { currentMonth.value = 1; currentYear.value++ }
  else { currentMonth.value++ }
  selectedDate.value = null
  loadCalendarData()
}

function goToday() {
  currentYear.value = today.getFullYear()
  currentMonth.value = today.getMonth() + 1
  selectedDate.value = { year: today.getFullYear(), month: today.getMonth() + 1, day: today.getDate() }
  loadCalendarData()
}

function formatDetailDate(dateStr) {
  const d = new Date(dateStr)
  const weekDayNames = ['日', '一', '二', '三', '四', '五', '六']
  return `${d.getMonth() + 1}月${d.getDate()}日 周${weekDayNames[d.getDay()]}`
}

function priorityColor(p) {
  const map = { urgent: '#FF7043', high: '#EF5350', medium: '#FFA726', low: '#66BB6A' }
  return map[p] || '#9E9E9E'
}

function priorityLabel(p) {
  const map = { urgent: '紧急', high: '高', medium: '中', low: '低' }
  return map[p] || p
}

function statusColor(s) {
  const map = { todo: 'grey', in_progress: 'info', done: 'success', overdue: 'error' }
  return map[s] || 'grey'
}

function statusLabel(s) {
  const map = { todo: '待办', in_progress: '进行中', done: '已完成', overdue: '已逾期' }
  return map[s] || s
}

onMounted(() => {
  loadCalendarData()
})
</script>

<style scoped>
.calendar-page {
  height: calc(100vh - 32px);
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

/* 顶部工具栏 */
.calendar-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: #fff;
}

.toolbar-left {
  display: flex;
  align-items: center;
}

/* 主体：日历 + 侧栏 */
.calendar-body {
  flex: 1;
  display: flex;
  overflow: hidden;
  border-top: 1px solid #E8E8E8;
}

/* 左侧日历 */
.calendar-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 8px;
  min-width: 0;
}

.weekday-row {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  text-align: center;
  padding: 8px 0;
  border-bottom: 1px solid #E8E8E8;
}

.weekday-cell {
  font-size: 13px;
  color: #888;
  font-weight: 600;
}

.calendar-grid {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  grid-template-rows: repeat(6, 1fr);
  gap: 3px;
  padding-top: 3px;
}

.day-cell {
  border: 1px solid #EEEEEE;
  border-radius: 8px;
  padding: 6px 8px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.day-cell:hover {
  background: #F5F8FF;
  border-color: #90CAF9;
}

.day-cell--other-month {
  opacity: 0.3;
  pointer-events: none;
}

.day-cell--today {
  background: #E3F2FD;
  border: 2px solid #1565C0;
}

.day-cell--selected {
  background: #1565C0 !important;
  border-color: #1565C0 !important;
}

.day-cell--selected .day-number {
  color: #fff !important;
  font-weight: 700;
}

.day-cell--selected .day-item-mini {
  color: rgba(255,255,255,0.9);
  background: rgba(255,255,255,0.2);
}

.day-top {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 2px;
}

.day-number {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  line-height: 1;
}

/* 日历格子内的任务条目 */
.day-items {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.day-item-mini {
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.5;
  cursor: default;
}

.day-item-mini--task {
  background: #E3F2FD;
  color: #1565C0;
}

.day-item-mini--deadline {
  background: #FFF3E0;
  color: #E65100;
}

.day-more-text {
  font-size: 10px;
  color: #999;
  padding-left: 5px;
}

/* 右侧面板 */
.calendar-sidebar {
  width: 320px;
  flex-shrink: 0;
  border-left: 1px solid #E8E8E8;
  background: #FAFBFC;
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sidebar-list {
  flex: 1;
  overflow-y: auto;
}

.sidebar-item {
  display: flex;
  align-items: flex-start;
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 4px;
  background: #fff;
  border: 1px solid #EEEEEE;
  transition: box-shadow 0.15s;
  gap: 10px;
}

.sidebar-item:hover {
  box-shadow: 0 1px 4px rgba(0,0,0,0.08);
}

.sidebar-item-left {
  padding-top: 2px;
  flex-shrink: 0;
}

.sidebar-item-center {
  flex: 1;
  min-width: 0;
}

.sidebar-item-title {
  font-size: 14px;
  font-weight: 500;
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-item-meta {
  display: flex;
  align-items: center;
  margin-top: 4px;
  gap: 4px;
}

.sidebar-item-right {
  flex-shrink: 0;
  padding-top: 2px;
}

.empty-hint {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #999;
}
</style>
