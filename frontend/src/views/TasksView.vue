<template>
  <section class="tasks-page">
    <div class="tasks-shell">
      <header class="tasks-header">
        <div class="tasks-header__main">
          <div class="title-mark"><v-icon icon="mdi-clipboard-text-clock-outline" size="27" /></div>
          <div>
            <div class="eyebrow">{{ $t('tasks.eyebrow') }}</div>
            <h1>{{ $t('tasks.title') }}</h1>
            <p>{{ $t('tasks.subtitle') }}</p>
          </div>
        </div>

        <div class="tasks-header__side">
          <div class="task-overview" :aria-label="$t('tasks.title')">
            <div><strong>{{ tasks.length }}</strong><span>{{ $t('tasks.all') }}</span></div>
            <i></i>
            <div><strong>{{ todoCount }}</strong><span>{{ $t('tasks.todo') }}</span></div>
            <i></i>
            <div><strong>{{ processCount }}</strong><span>{{ $t('tasks.process') }}</span></div>
          </div>
          <div class="header-actions">
            <v-btn class="create-task-btn" color="primary" prepend-icon="mdi-plus" size="large" @click="openCreate">{{ $t('tasks.newTask') }}</v-btn>
          </div>
        </div>
      </header>

      <!-- 视图切换：全部任务 / 个人 Deadline + 紧急筛选（URL query 驱动，可分享可重定向） -->
      <div class="view-switch">
        <v-chip-group
          :model-value="activeTab"
          mandatory
          selected-class="filter-chip--selected"
          @update:model-value="setView({ tab: $event === 'deadlines' ? 'deadlines' : null })"
        >
          <v-chip value="all" variant="text" prepend-icon="mdi-check-circle-outline">{{ $t('tasks.tabAll') }}</v-chip>
          <v-chip value="deadlines" variant="text" prepend-icon="mdi-calendar-alert-outline">{{ $t('tasks.tabDeadlines') }}</v-chip>
        </v-chip-group>
        <v-chip
          class="urgent-toggle"
          :color="urgentOnly ? 'error' : undefined"
          :variant="urgentOnly ? 'flat' : 'text'"
          prepend-icon="mdi-lightning-bolt-outline"
          @click="setView({ filter: urgentOnly ? null : 'urgent' })"
        >
          {{ $t('tasks.filterUrgent') }}
        </v-chip>
      </div>

      <template v-if="activeTab === 'all'">
      <div class="task-filters">
        <div class="filter-block">
          <span class="filter-label">{{ $t('tasks.typeLabel') }}</span>
          <v-chip-group v-model="typeFilter" mandatory selected-class="filter-chip--selected">
            <v-chip value="all" variant="text">{{ $t('tasks.allTypes') }}</v-chip>
            <v-chip value="todo" variant="text" prepend-icon="mdi-checkbox-marked-circle-outline">{{ $t('tasks.todoType') }}</v-chip>
            <v-chip value="process" variant="text" prepend-icon="mdi-timeline-text-outline">{{ $t('tasks.processType') }}</v-chip>
          </v-chip-group>
        </div>
        <div class="filter-block filter-block--status">
          <span class="filter-label">{{ $t('tasks.statusLabel') }}</span>
          <v-chip-group v-model="statusFilter" mandatory selected-class="filter-chip--selected">
            <v-chip value="all" size="small" variant="text">{{ $t('tasks.allStatus') }}</v-chip>
            <v-chip value="todo" size="small" variant="text">{{ $t('common.pending') }}</v-chip>
            <v-chip value="in_progress" size="small" variant="text">{{ $t('common.inProgress') }}</v-chip>
            <v-chip value="done" size="small" variant="text">{{ $t('common.done') }}</v-chip>
          </v-chip-group>
        </div>
      </div>

    <div v-if="loading" class="task-empty">
      <v-progress-circular indeterminate color="primary" />
      <span>{{ $t('common.loadingTasks') }}</span>
    </div>

    <div v-else-if="filteredTasks.length" class="task-grid">
      <v-card
        v-for="task in filteredTasks"
        :key="task.id"
        :id="`task-card-${task.id}`"
        class="task-card"
        :class="{
          'task-card--process': task.task_type === 'process',
          'task-card--focused': focusedTaskId === task.id,
        }"
        rounded="xl"
        elevation="0"
      >
        <div class="task-card__top">
          <v-checkbox
            class="task-check"
            :model-value="task.status === 'done'"
            :color="task.status === 'overdue' ? 'error' : 'primary'"
            density="compact"
            hide-details
            @update:model-value="toggleDone(task)"
          />
          <div class="task-card__title">
            <div class="d-flex align-center ga-2 flex-wrap">
              <h2>{{ task.title }}</h2>
              <v-chip
                size="x-small"
                :color="task.task_type === 'process' ? 'deep-purple' : 'primary'"
                variant="tonal"
              >
                {{ task.task_type === 'process' ? $t('tasks.processType') : $t('tasks.todoType') }}
              </v-chip>
            </div>
            <p v-if="task.description">{{ task.description }}</p>
          </div>
          <div class="task-card__actions">
            <v-btn
              v-if="task.task_type === 'process'"
              prepend-icon="mdi-plus"
              color="deep-purple"
              variant="tonal"
              size="small"
              @click="openSubtask(task)"
            >
              {{ $t('tasks.addSubtask') }}
            </v-btn>
            <v-btn
              class="delete-task-btn"
              icon="mdi-delete-outline"
              color="error"
              variant="tonal"
              size="small"
              :aria-label="$t('tasks.deleteTask')"
              @click="requestDelete(task)"
            />
          </div>
        </div>

        <div class="task-meta">
          <span v-if="task.subject"><v-icon icon="mdi-tag-outline" size="14" />{{ task.subject }}</span>
          <span><v-icon icon="mdi-flag-outline" size="14" />{{ priorityLabel(task.priority) }}</span>
          <span v-if="task.deadline"><v-icon icon="mdi-calendar-outline" size="14" />{{ formatDate(task.deadline) }}</span>
          <span v-if="task.estimated_hours"><v-icon icon="mdi-clock-outline" size="14" />{{ $t('tasks.hoursUnit', { n: task.estimated_hours }) }}</span>
        </div>

        <div class="progress-block">
          <div><span>{{ task.task_type === 'process' ? $t('tasks.processProgress') : $t('tasks.taskProgress') }}</span><strong>{{ displayProgress(task) }}%</strong></div>
          <v-progress-linear
            :model-value="displayProgress(task)"
            :color="task.status === 'overdue' ? 'error' : (task.task_type === 'process' ? 'deep-purple' : 'primary')"
            height="7"
            rounded
          />
        </div>

        <div v-if="task.task_type === 'process'" class="subtask-section">
          <div class="subtask-heading">
            <span>{{ $t('tasks.processNode') }}</span>
            <small>{{ $t('common.items', { n: task.subtasks?.length || 0 }) }}</small>
          </div>

          <div v-if="task.subtasks?.length" class="subtask-list">
            <div
              v-for="(subtask, index) in task.subtasks"
              :key="subtask.id"
              class="subtask-row"
              :class="{ 'subtask-row--focused': focusedTaskId === subtask.id }"
            >
              <span class="subtask-index">{{ index + 1 }}</span>
              <v-checkbox
                :model-value="subtask.status === 'done'"
                density="compact"
                hide-details
                @update:model-value="toggleDone(subtask)"
              />
              <div class="subtask-copy">
                <div>
                  <strong>{{ subtask.title }}</strong>
                </div>
                <small>{{ subtask.deadline ? formatDate(subtask.deadline) : $t('tasks.noDate') }}</small>
              </div>
              <v-chip size="x-small" :color="priorityColor(subtask.priority)" variant="tonal">
                {{ priorityLabel(subtask.priority) }}
              </v-chip>
              <v-btn
                class="delete-subtask-btn"
                icon="mdi-delete-outline"
                color="error"
                variant="text"
                density="comfortable"
                size="small"
                :aria-label="$t('tasks.deleteSubtask')"
                @click="requestDeleteSubtask(subtask)"
              />
            </div>
          </div>

          <button v-else type="button" class="add-first-subtask" @click="openSubtask(task)">
            <v-icon icon="mdi-plus-circle-outline" />
            {{ $t('tasks.addFirstNode') }}
          </button>
        </div>

      </v-card>
    </div>

    <div v-else class="task-empty">
      <v-icon icon="mdi-clipboard-text-outline" size="58" color="grey-lighten-1" />
      <strong>{{ $t('tasks.emptyTitle') }}</strong>
      <span>{{ $t('tasks.emptyDesc') }}</span>
      <v-btn color="primary" variant="tonal" @click="openCreate">{{ $t('tasks.createTask') }}</v-btn>
    </div>
      </template>

      <!-- 个人 Deadline Tab（合并自 DeadlinesView） -->
      <template v-else>
        <div class="deadline-filters">
          <v-chip-group v-model="deadlineStatusFilter" mandatory selected-class="filter-chip--selected">
            <v-chip value="all" size="small" variant="text">{{ $t('common.all') }}</v-chip>
            <v-chip value="pending" size="small" variant="text">{{ $t('deadlines.pending') }}</v-chip>
            <v-chip value="done" size="small" variant="text">{{ $t('deadlines.done') }}</v-chip>
            <v-chip value="overdue" size="small" variant="text">{{ $t('deadlines.overdue') }}</v-chip>
          </v-chip-group>
          <v-btn color="primary" prepend-icon="mdi-plus" size="small" @click="openDeadlineCreate">{{ $t('deadlines.add') }}</v-btn>
        </div>

        <v-alert v-if="collision?.overload" type="warning" variant="tonal" closable class="mb-4">
          {{ collision.suggestion }}
        </v-alert>

        <div class="deadline-layout">
          <div class="deadline-main">
            <div v-if="loading" class="task-empty">
              <v-progress-circular indeterminate color="primary" />
              <span>{{ $t('common.loadingTasks') }}</span>
            </div>

            <div v-else-if="filteredDeadlines.length" class="deadline-list">
              <div
                v-for="d in filteredDeadlines"
                :key="d.id"
                :id="`deadline-item-${d.id}`"
                class="deadline-row"
                :class="{ 'deadline-row--overdue': d.status === 'overdue', 'deadline-row--focused': focusedDeadlineId === d.id }"
              >
                <v-btn
                  class="deadline-check"
                  :icon="d.status === 'done' ? 'mdi-check-circle' : 'mdi-circle-outline'"
                  :color="deadlineStatusColor(d.status)"
                  variant="text"
                  density="comfortable"
                  :aria-label="$t('deadlines.done')"
                  @click="toggleDeadlineDone(d)"
                />
                <div class="deadline-copy">
                  <strong>{{ d.title }}</strong>
                  <small>
                    <span v-if="d.source"><v-icon icon="mdi-link-variant" size="12" />{{ d.source }}</span>
                    <span v-if="d.subject">{{ d.subject }}</span>
                    <span v-if="d.description">{{ d.description }}</span>
                  </small>
                </div>
                <div class="deadline-side">
                  <span class="deadline-date" :class="{ 'is-overdue': d.status === 'overdue' }">{{ formatDeadlineDate(d.due_date) }}</span>
                  <v-chip size="x-small" :color="priorityColor(d.priority)" variant="tonal">{{ priorityLabel(d.priority) }}</v-chip>
                </div>
              </div>
            </div>

            <div v-else class="task-empty">
              <v-icon icon="mdi-calendar-check-outline" size="58" color="grey-lighten-1" />
              <strong>{{ $t('deadlines.empty') }}</strong>
              <v-btn color="primary" variant="tonal" @click="openDeadlineCreate">{{ $t('deadlines.add') }}</v-btn>
            </div>
          </div>

          <aside class="deadline-aside">
            <div class="deadline-panel">
              <div class="deadline-panel__title">{{ $t('deadlines.upcoming') }}</div>
              <div v-if="upcomingDeadlines.length" class="deadline-panel__list">
                <div v-for="d in upcomingDeadlines" :key="d.id" class="deadline-panel__row">
                  <span>{{ d.title }}</span>
                  <small>{{ $t('common.daysLater', { n: deadlineDaysLeft(d.due_date) }) }} · {{ d.subject || $t('common.noSubject') }}</small>
                </div>
              </div>
              <div v-else class="deadline-panel__empty">{{ $t('deadlines.upcomingEmpty') }}</div>
            </div>

            <div class="deadline-panel">
              <div class="deadline-panel__title">{{ $t('deadlines.collision') }}</div>
              <v-text-field
                v-model="checkDate"
                :label="$t('deadlines.checkDateLabel')"
                type="date"
                variant="outlined"
                density="compact"
                hide-details
                class="mb-2"
                @keydown.enter="checkCollision"
              />
              <v-btn block variant="tonal" color="primary" size="small" @click="checkCollision">{{ $t('deadlines.check') }}</v-btn>
              <div v-if="collision" class="deadline-panel__result">
                {{ $t('deadlines.collisionResult', { date: collision.date, count: collision.count }) }}
                <v-chip v-if="collision.overload" size="x-small" color="warning" class="ml-1">{{ $t('deadlines.overload') }}</v-chip>
                <v-chip v-else size="x-small" color="success" class="ml-1">{{ $t('deadlines.reasonable') }}</v-chip>
              </div>
            </div>
          </aside>
        </div>
      </template>
    </div>

    <v-dialog v-model="createDialog" max-width="580">
      <v-card rounded="xl" :title="$t('tasks.dialogTitle')">
        <v-card-text>
          <div class="type-selector">
            <button
              type="button"
              :class="{ active: form.task_type === 'todo' }"
              @click="form.task_type = 'todo'"
            >
              <v-icon icon="mdi-checkbox-marked-circle-outline" />
              <span><strong>{{ $t('tasks.todoType') }}</strong></span>
            </button>
            <button
              type="button"
              :class="{ active: form.task_type === 'process' }"
              @click="form.task_type = 'process'"
            >
              <v-icon icon="mdi-timeline-text-outline" />
              <span><strong>{{ $t('tasks.processType') }}</strong></span>
            </button>
          </div>

          <v-text-field v-model="form.title" :label="$t('tasks.taskName')" variant="outlined" density="comfortable" class="mb-2" />
          <v-textarea v-model="form.description" :label="$t('tasks.description')" variant="outlined" density="comfortable" rows="2" class="mb-2" />
          <v-text-field v-model="form.subject" :label="$t('tasks.subject')" variant="outlined" density="comfortable" class="mb-2" />
          <v-row dense>
            <v-col cols="12" sm="6">
              <v-select
                v-model="form.priority"
                :label="$t('tasks.priority')"
                :items="priorityOptions"
                :item-title="priorityTitle"
                item-value="value"
                variant="outlined"
                density="comfortable"
              />
            </v-col>
            <v-col cols="12" sm="6">
              <v-text-field v-model="form.deadline" :label="$t('tasks.deadline')" type="date" variant="outlined" density="comfortable" />
            </v-col>
          </v-row>
          <v-row dense>
            <v-col cols="12" sm="6">
              <v-text-field
                v-model="form.deadline_time"
                :label="$t('tasks.deadlineTime')"
                type="time"
                variant="outlined"
                density="comfortable"
                :disabled="!form.deadline"
                :hint="$t('tasks.deadlineTimeHint')"
                persistent-hint
              />
            </v-col>
            <v-col cols="12" sm="6">
              <v-select
                v-model="form.reminder_mode"
                :label="$t('tasks.reminderMode')"
                :items="reminderModeOptions"
                item-title="title"
                item-value="value"
                variant="outlined"
                density="comfortable"
                :disabled="!form.deadline"
              />
            </v-col>
          </v-row>
          <div v-if="form.deadline && form.reminder_mode === 'custom'" class="reminder-offsets-box">
            <ReminderOffsetsEditor v-model="form.reminder_offsets" />
          </div>
          <v-text-field v-model="form.estimated_hours" :label="$t('tasks.estimatedHours')" type="number" min="0" variant="outlined" density="comfortable" />
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" @click="createDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="primary" :loading="saving" :disabled="!canCreate" @click="createTask">{{ $t('common.create') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="subtaskDialog" max-width="520">
      <v-card rounded="xl">
        <v-card-title class="pt-5 px-6">{{ $t('tasks.subtaskDialogTitle') }}</v-card-title>
        <v-card-subtitle class="px-6">{{ selectedParent?.title }}</v-card-subtitle>
        <v-card-text class="pt-5">
          <v-text-field v-model="subtaskForm.title" :label="$t('tasks.subtaskName')" variant="outlined" density="comfortable" class="mb-2" />
          <v-textarea v-model="subtaskForm.description" :label="$t('tasks.description')" rows="2" variant="outlined" density="comfortable" class="mb-2" />
          <v-row dense>
            <v-col cols="12" sm="6">
              <v-select
                v-model="subtaskForm.priority"
                :label="$t('tasks.priority')"
                :items="priorityOptions"
                :item-title="priorityTitle"
                item-value="value"
                variant="outlined"
                density="comfortable"
              />
            </v-col>
            <v-col cols="12" sm="6">
              <v-text-field v-model="subtaskForm.deadline" :label="$t('tasks.nodeDate')" type="date" variant="outlined" density="comfortable" />
            </v-col>
          </v-row>
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" @click="subtaskDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="deep-purple" :loading="saving" :disabled="!subtaskForm.title" @click="createSubtask">{{ $t('tasks.addNode') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="deleteDialog" max-width="440">
      <v-card rounded="xl">
        <v-card-title class="pt-5 px-6">{{ $t('tasks.deleteDialogTitle') }}</v-card-title>
        <v-card-text class="px-6 pt-3">
          <p>{{ $t('tasks.deleteConfirm', { title: selectedTask?.title }) }}</p>
          <v-alert v-if="selectedTask?.task_type === 'process'" type="warning" variant="tonal" density="compact" class="mt-4">
            {{ $t('tasks.deleteProcessWarn') }}
          </v-alert>
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" :disabled="deleting" @click="deleteDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="error" variant="flat" :loading="deleting" @click="confirmDelete">{{ $t('tasks.confirmDelete') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="subtaskDeleteDialog" max-width="440">
      <v-card rounded="xl">
        <v-card-title class="pt-5 px-6">{{ $t('tasks.deleteSubtaskDialogTitle') }}</v-card-title>
        <v-card-text class="px-6 pt-3">
          <p>{{ $t('tasks.deleteSubtaskConfirm', { title: selectedSubtask?.title }) }}</p>
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" :disabled="deletingSubtask" @click="subtaskDeleteDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="error" variant="flat" :loading="deletingSubtask" @click="confirmDeleteSubtask">{{ $t('tasks.confirmDelete') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 新建 Deadline 对话框（合并自 DeadlinesView） -->
    <v-dialog v-model="deadlineDialog" max-width="500">
      <v-card rounded="xl" :title="$t('deadlines.dialogTitle')">
        <v-card-text>
          <v-text-field v-model="deadlineForm.title" :label="$t('deadlines.titleField')" variant="outlined" density="comfortable" class="mb-2" />
          <v-text-field v-model="deadlineForm.source" :label="$t('deadlines.source')" variant="outlined" density="comfortable" class="mb-2" />
          <v-text-field v-model="deadlineForm.subject" :label="$t('deadlines.subject')" variant="outlined" density="comfortable" class="mb-2" />
          <v-row dense>
            <v-col cols="12" sm="6">
              <v-text-field v-model="deadlineForm.due_date" :label="$t('deadlines.dueDate')" type="date" variant="outlined" density="comfortable" />
            </v-col>
            <v-col cols="12" sm="6">
              <v-select
                v-model="deadlineForm.priority"
                :label="$t('deadlines.priority')"
                :items="priorityOptions"
                :item-title="priorityTitle"
                item-value="value"
                variant="outlined"
                density="comfortable"
              />
            </v-col>
          </v-row>
          <v-textarea v-model="deadlineForm.description" :label="$t('deadlines.note')" variant="outlined" density="comfortable" rows="2" />
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" @click="deadlineDialog = false">{{ $t('common.cancel') }}</v-btn>
          <v-btn color="primary" :loading="saving" :disabled="!deadlineForm.title || !deadlineForm.due_date" @click="createDeadline">{{ $t('common.add') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="errorVisible" color="error" timeout="3500">{{ errorMessage }}</v-snackbar>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { authFetch, api } from '@/stores/auth'
import { notifyTasksChanged, onTasksChanged } from '@/services/taskSync'
import { daysUntil } from '@/utils/tasks'
import ReminderOffsetsEditor from '@/components/ReminderOffsetsEditor.vue'

const API_BASE = '/api'
const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const tasks = ref([])
const loading = ref(true)
const saving = ref(false)
const typeFilter = ref('all')
const statusFilter = ref('all')
const createDialog = ref(false)
const subtaskDialog = ref(false)
const selectedParent = ref(null)
const deleteDialog = ref(false)
const selectedTask = ref(null)
const deleting = ref(false)
const subtaskDeleteDialog = ref(false)
const selectedSubtask = ref(null)
const deletingSubtask = ref(false)
const errorVisible = ref(false)
const errorMessage = ref('')
const focusedTaskId = ref(null)  // 从提醒弹窗跳转后要高亮的任务/子任务 id

// ---- 视图状态（URL query 驱动）：tab=all|deadlines，filter=urgent ----
const activeTab = computed(() => (route.query.tab === 'deadlines' ? 'deadlines' : 'all'))
const urgentOnly = computed(() => route.query.filter === 'urgent')
function setView(patch) {
  const query = { ...route.query }
  for (const [key, value] of Object.entries(patch)) {
    if (value == null) delete query[key]
    else query[key] = value
  }
  router.replace({ query })
}
// 紧急判定：tasks 与 deadlines 通用（对齐手册口径）
function isUrgent(item) {
  return item?.priority === 'urgent' || item?.status === 'overdue'
}

// ---- deadlines Tab 状态（合并自 DeadlinesView） ----
const deadlines = ref([])
const upcomingDeadlines = ref([])
const collision = ref(null)
const checkDate = ref('')
const deadlineStatusFilter = ref('all')
const deadlineDialog = ref(false)
const focusedDeadlineId = ref(null)
const emptyDeadlineForm = () => ({ title: '', source: '', subject: '', due_date: '', priority: 'medium', description: '' })
const deadlineForm = ref(emptyDeadlineForm())

const priorityOptions = [
  { titleKey: 'common.low', value: 'low' },
  { titleKey: 'common.medium', value: 'medium' },
  { titleKey: 'common.high', value: 'high' },
  { titleKey: 'common.urgent', value: 'urgent' },
]

const emptyForm = () => ({
  task_type: 'todo', title: '', description: '', subject: '', priority: 'medium', deadline: '', estimated_hours: 0,
  deadline_time: '', reminder_mode: 'inherit', reminder_offsets: [5, 1440],
})
const emptySubtaskForm = () => ({ title: '', description: '', priority: 'medium', deadline: '' })
const form = ref(emptyForm())
const subtaskForm = ref(emptySubtaskForm())

// 任务级提醒三态：继承用户默认(null) / 自定义分钟数组 / 关闭([])
const reminderModeOptions = computed(() => [
  { title: t('tasks.reminderInherit'), value: 'inherit' },
  { title: t('tasks.reminderCustom'), value: 'custom' },
  { title: t('tasks.reminderOff'), value: 'off' },
])

const filteredTasks = computed(() => tasks.value.filter((task) => {
  const matchesType = typeFilter.value === 'all' || task.task_type === typeFilter.value
  const matchesStatus = statusFilter.value === 'all' || task.status === statusFilter.value
  const matchesUrgent = !urgentOnly.value || isUrgent(task)
  return matchesType && matchesStatus && matchesUrgent
}))
const filteredDeadlines = computed(() => deadlines.value.filter((d) => {
  const matchesStatus = deadlineStatusFilter.value === 'all' || d.status === deadlineStatusFilter.value
  const matchesUrgent = !urgentOnly.value || isUrgent(d)
  return matchesStatus && matchesUrgent
}))
const todoCount = computed(() => tasks.value.filter((task) => task.task_type !== 'process').length)
const processCount = computed(() => tasks.value.filter((task) => task.task_type === 'process').length)

const canCreate = computed(() => Boolean(form.value.title && (form.value.task_type !== 'process' || form.value.deadline)))

function priorityColor(priority) {
  return { low: 'grey', medium: 'primary', high: 'warning', urgent: 'error' }[priority] || 'grey'
}

function priorityTitle(item) {
  return item.titleKey ? t(item.titleKey) : item.title
}

function priorityLabel(priority) {
  const keyMap = { low: 'low', medium: 'medium', high: 'high', urgent: 'urgent' }
  return t(`common.${keyMap[priority] || ''}`) || priority
}

function formatDate(value) {
  const date = new Date(`${value}T00:00:00`)
  return t('common.yearMonthDay', { year: date.getFullYear(), month: date.getMonth() + 1, day: date.getDate() })
}

function displayProgress(task) {
  if (task.task_type !== 'process' || !task.subtasks?.length) return Number(task.progress || 0)
  const total = task.subtasks.reduce((sum, item) => sum + (item.status === 'done' ? 100 : Number(item.progress || 0)), 0)
  return Math.round(total / task.subtasks.length)
}

function showError(message) {
  errorMessage.value = message
  errorVisible.value = true
}

/** 处理提醒弹窗跳转的 focus 参数：定位并高亮对应任务卡片 / deadline 行 */
function handleFocus() {
  const focusId = route.query.focus
  if (!focusId) return
  const target = Number(focusId)

  // deadlines Tab：在 deadline 列表中定位
  if (activeTab.value === 'deadlines') {
    if (!deadlines.value.some((d) => d.id === target)) return
    focusedDeadlineId.value = target
    nextTick(() => {
      document.getElementById(`deadline-item-${target}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
    window.setTimeout(() => { focusedDeadlineId.value = null }, 2600)
    return
  }

  if (!tasks.value.length) return
  // 顶级任务直接匹配
  let card = tasks.value.find((task) => task.id === target)
  // 否则在子任务中查找其父级卡片
  if (!card) {
    for (const task of tasks.value) {
      if ((task.subtasks || []).some((s) => s.id === target)) {
        card = task
        break
      }
    }
  }
  if (!card) return

  focusedTaskId.value = target
  nextTick(() => {
    document.getElementById(`task-card-${card.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
  window.setTimeout(() => { focusedTaskId.value = null }, 2600)
}

async function loadTasks() {
  loading.value = true
  try {
    const [taskData, deadlineData, upcomingData] = await Promise.all([
      api(`${API_BASE}/tasks`),
      api(`${API_BASE}/deadlines`),
      api(`${API_BASE}/deadlines/upcoming?days=7`),
    ])
    tasks.value = Array.isArray(taskData) ? taskData : []
    deadlines.value = Array.isArray(deadlineData) ? deadlineData : []
    upcomingDeadlines.value = Array.isArray(upcomingData) ? upcomingData : []
  } catch (error) {
    showError(t('tasks.loadFail', { msg: error.message }))
  } finally {
    loading.value = false
    handleFocus()  // 数据就绪后定位提醒跳转的目标
  }
}

// 已在任务页时再次跳转（同路由不同 query）也能响应 focus；切 Tab 后同样重新定位
watch(() => route.query.focus, () => handleFocus())
watch(activeTab, () => handleFocus())

function openCreate() {
  form.value = emptyForm()
  createDialog.value = true
}

function openSubtask(task) {
  selectedParent.value = task
  subtaskForm.value = { ...emptySubtaskForm(), deadline: task.deadline || '' }
  subtaskDialog.value = true
}

function requestDelete(task) {
  selectedTask.value = task
  deleteDialog.value = true
}

function requestDeleteSubtask(subtask) {
  selectedSubtask.value = subtask
  subtaskDeleteDialog.value = true
}

async function confirmDelete() {
  if (!selectedTask.value) return
  deleting.value = true
  try {
    const response = await authFetch(`${API_BASE}/tasks/${selectedTask.value.id}`, { method: 'DELETE' })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || `HTTP ${response.status}`)
    }
    deleteDialog.value = false
    selectedTask.value = null
    notifyTasksChanged()
  } catch (error) {
    showError(t('tasks.deleteFail', { msg: error.message }))
  } finally {
    deleting.value = false
  }
}

async function confirmDeleteSubtask() {
  if (!selectedSubtask.value) return
  deletingSubtask.value = true
  try {
    const response = await authFetch(`${API_BASE}/tasks/sub-tasks/${selectedSubtask.value.id}`, { method: 'DELETE' })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || `HTTP ${response.status}`)
    }
    subtaskDeleteDialog.value = false
    selectedSubtask.value = null
    notifyTasksChanged()
  } catch (error) {
    showError(t('tasks.deleteSubtaskFail', { msg: error.message }))
  } finally {
    deletingSubtask.value = false
  }
}

async function postTask(payload) {
  const response = await authFetch(`${API_BASE}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${response.status}`)
  }
  return response.json()
}

async function createTask() {
  saving.value = true
  try {
    // 组装 payload：剥掉前端辅助字段；填了时分则拼成 datetime，否则沿用旧行为只传日期
    const { deadline_time, reminder_mode, reminder_offsets, ...base } = form.value
    const payload = { ...base }
    if (payload.deadline && deadline_time) {
      payload.deadline = `${payload.deadline}T${deadline_time}:00`
    }
    if (payload.deadline) {
      if (reminder_mode === 'off') payload.reminder_offsets_minutes = []
      else if (reminder_mode === 'custom') {
        payload.reminder_offsets_minutes = [...reminder_offsets].sort((a, b) => a - b)
      } else payload.reminder_offsets_minutes = null  // 继承用户默认
    }
    await postTask(payload)
    createDialog.value = false
    notifyTasksChanged()
  } catch (error) {
    showError(t('tasks.createFail', { msg: error.message }))
  } finally {
    saving.value = false
  }
}

async function createSubtask() {
  if (!selectedParent.value) return
  saving.value = true
  try {
    const response = await authFetch(`${API_BASE}/tasks/sub-tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task_id: selectedParent.value.id,
        name: subtaskForm.value.title,
        description: subtaskForm.value.description || '',
        notice_time: subtaskForm.value.deadline || null,
        level: subtaskForm.value.priority || 'medium',
        status: 'pending',
      }),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || `HTTP ${response.status}`)
    }
    subtaskDialog.value = false
    notifyTasksChanged()
  } catch (error) {
    showError(t('tasks.addSubtaskFail', { msg: error.message }))
  } finally {
    saving.value = false
  }
}

async function toggleDone(task) {
  const nextStatus = task.status === 'done' ? 'todo' : 'done'
  const endpoint = task.sub_task_source
    ? `${API_BASE}/tasks/sub-tasks/${task.id}`
    : `${API_BASE}/tasks/${task.id}`
  try {
    const response = await authFetch(endpoint, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: nextStatus, progress: nextStatus === 'done' ? 100 : 0 }),
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    notifyTasksChanged()
  } catch (error) {
    showError(t('tasks.updateFail', { msg: error.message }))
  }
}

// ---- deadlines Tab 操作（合并自 DeadlinesView，统一走 api() 获得 401 拦截） ----
function deadlineStatusColor(s) {
  return { pending: 'warning', done: 'success', overdue: 'error' }[s] || 'grey'
}

function formatDeadlineDate(value) {
  if (!value) return ''
  const date = new Date(`${value}T00:00:00`)
  return t('common.monthDay', { month: date.getMonth() + 1, day: date.getDate() })
}

function deadlineDaysLeft(value) {
  return daysUntil(value)
}

function openDeadlineCreate() {
  deadlineForm.value = emptyDeadlineForm()
  deadlineDialog.value = true
}

async function createDeadline() {
  saving.value = true
  try {
    await api(`${API_BASE}/deadlines`, { method: 'POST', body: JSON.stringify(deadlineForm.value) })
    deadlineDialog.value = false
    notifyTasksChanged()  // 触发本页 reload + App 铃铛/日历联动
  } catch (error) {
    showError(error.message)
  } finally {
    saving.value = false
  }
}

async function toggleDeadlineDone(d) {
  const nextStatus = d.status === 'done' ? 'pending' : 'done'
  try {
    await api(`${API_BASE}/deadlines/${d.id}`, { method: 'PUT', body: JSON.stringify({ status: nextStatus }) })
    notifyTasksChanged()
  } catch (error) {
    showError(error.message)
  }
}

async function checkCollision() {
  if (!checkDate.value) return
  try {
    collision.value = await api(`${API_BASE}/deadlines/check/collisions?date=${checkDate.value}`)
  } catch (error) {
    showError(error.message)
  }
}

let stopTaskSync
watch(() => route.query.create, (value) => {
  if (value !== '1') return
  openCreate()
  const query = { ...route.query }
  delete query.create
  router.replace({ query })
}, { immediate: true })

onMounted(() => {
  loadTasks()
  stopTaskSync = onTasksChanged(loadTasks)
})
onBeforeUnmount(() => stopTaskSync?.())
</script>

<style scoped>
.tasks-page {
  position: relative;
  min-height: calc(100vh - 64px);
  overflow: hidden;
  padding: clamp(28px, 4vw, 58px) clamp(24px, 5vw, 80px) 120px;
  color: var(--ib-text);
  background: var(--ib-background);
}
.tasks-page::before {
  position: absolute;
  inset: 0;
  pointer-events: none;
  content: '';
  background-size: 32px 32px;
  mask-image: linear-gradient(to bottom, var(--ib-text), transparent 58%);
}
.tasks-shell { position: relative; z-index: 1; width: 100%; max-width: 1480px; margin: 0 auto; }
.tasks-header {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
  overflow: hidden;
  padding: 28px 30px;
  border: 1px solid var(--ib-border);
  border-radius: 26px;
  background: var(--ib-surface);
  box-shadow: var(--ib-shadow-card);
}
.tasks-header::after {
  position: absolute;
  top: -95px;
  right: -60px;
  width: 280px;
  height: 280px;
  border-radius: 50%;
  content: '';
  background: var(--ib-primary-soft);
}
.tasks-header__main, .tasks-header__side { position: relative; z-index: 1; display: flex; align-items: center; }
.tasks-header__main { flex: 1 1 auto; gap: 17px; min-width: 0; }
.tasks-header__main > div:last-child { min-width: 0; }
.tasks-header__side { flex-shrink: 0; gap: 20px; }
.header-actions { display: flex; align-items: center; gap: 9px; }
.title-mark {
  width: 58px;
  height: 58px;
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 18px;
  color: var(--ib-on-primary);
  background: linear-gradient(145deg, var(--ib-primary), var(--ib-primary));
  box-shadow: var(--ib-shadow-card);
}
.eyebrow { color: var(--ib-primary); font-size: 10px; font-weight: 800; letter-spacing: .18em; }
.tasks-header h1 { margin: 4px 0 0; color: var(--ib-text); font-size: clamp(29px, 3vw, 40px); font-weight: 780; line-height: 1.08; letter-spacing: -.045em; }
.tasks-header p { max-width: 650px; margin-top: 8px; color: var(--ib-text-secondary); font-size: 13px; line-height: 1.65; }
.task-overview {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 9px 15px;
  border: 1px solid var(--ib-border);
  border-radius: 16px;
  background: var(--ib-surface);
}
.task-overview div { min-width: 34px; text-align: center; }
.task-overview strong, .task-overview span { display: block; }
.task-overview strong { color: var(--ib-text); font-size: 16px; line-height: 1.2; }
.task-overview span { margin-top: 2px; color: var(--ib-text-muted); font-size: 9px; }
.task-overview i { width: 1px; height: 24px; background: var(--ib-surface-subtle); }
.create-task-btn { min-width: 128px; box-shadow: var(--ib-shadow-card); }
.task-filters {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin: 22px 0 20px;
  padding: 13px 17px;
  border: 1px solid var(--ib-border);
  border-radius: 19px;
  background: var(--ib-surface);
  box-shadow: var(--ib-shadow-card);
  backdrop-filter: blur(12px);
}
.filter-block { display: flex; align-items: center; gap: 10px; min-width: 0; }
.filter-label { flex: 0 0 auto; padding-right: 10px; border-right: 1px solid var(--ib-border); color: var(--ib-text-muted); font-size: 9px; font-weight: 750; letter-spacing: .08em; }
.task-filters :deep(.v-chip-group) { padding: 0; }
.task-filters :deep(.v-chip) { color: var(--ib-text-secondary); font-size: 11px; transition: color .2s, background .2s; }
.task-filters :deep(.filter-chip--selected) { color: var(--ib-primary) !important; background: var(--ib-primary-soft) !important; }
.task-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.task-card {
  position: relative;
  overflow: hidden;
  min-width: 0;
  padding: 22px 23px 21px;
  border: 1px solid var(--ib-border);
  border-radius: 22px !important;
  background: var(--ib-surface) !important;
  box-shadow: var(--ib-shadow-card);
  transition: transform .2s ease, border-color .2s ease, box-shadow .2s ease;
}
.task-card::before { position: absolute; top: 0; left: 0; width: 100%; height: 4px; content: ''; background: linear-gradient(90deg, var(--ib-primary), var(--ib-primary)); }
.task-card:hover { transform: translateY(-2px); border-color: var(--ib-border); box-shadow: var(--ib-shadow-card); }
.task-card--focused { border-color: var(--ib-primary) !important; box-shadow: var(--ib-shadow-card); }
.subtask-row--focused { background: var(--ib-primary-soft) !important; border-color: var(--ib-border) !important; }
.task-card--process { grid-column: span 2; border-color: var(--ib-border); }
.task-card--process::before { background: linear-gradient(90deg, var(--ib-primary), var(--ib-primary)); }
.task-card__top { display: flex; align-items: flex-start; gap: 12px; }
.task-card__actions { display: flex; flex: 0 0 auto; align-items: center; gap: 7px; }
.delete-task-btn { opacity: .78; }
.delete-task-btn:hover { opacity: 1; }
.task-check { flex: 0 0 auto; margin: -3px 0 0 -6px; }
.task-check :deep(.v-selection-control) { min-height: 36px; }
.task-card__title { flex: 1; min-width: 0; padding-top: 2px; }
.task-card__title h2 { overflow-wrap: anywhere; color: var(--ib-text); font-size: 17px; font-weight: 720; line-height: 1.4; }
.task-card__title p { margin-top: 7px; color: var(--ib-text-muted); font-size: 12px; line-height: 1.55; }
.task-meta { display: flex; flex-wrap: wrap; gap: 7px; margin: 17px 0 15px 42px; color: var(--ib-text-secondary); font-size: 10px; }
.task-meta span { display: inline-flex; align-items: center; gap: 5px; padding: 6px 9px; border-radius: 9px; background: var(--ib-primary-soft); }
.progress-block { margin-left: 42px; padding: 11px 12px 12px; border: 1px solid var(--ib-border); border-radius: 12px; background: var(--ib-primary-soft); }
.progress-block > div { display: flex; justify-content: space-between; margin-bottom: 7px; color: var(--ib-text-muted); font-size: 10px; }
.progress-block strong { color: var(--ib-text); font-size: 11px; }
.subtask-section { margin: 20px 0 0 42px; padding: 16px; border: 1px solid var(--ib-border); border-radius: 16px; background: linear-gradient(135deg, var(--ib-primary-soft), var(--ib-primary-soft)); }
.subtask-heading { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; color: var(--ib-text); font-size: 12px; font-weight: 720; }
.subtask-heading small { padding: 2px 7px; border-radius: 999px; color: var(--ib-text-muted); background: var(--ib-primary-soft); font-weight: 550; }
.subtask-list { display: flex; flex-direction: column; gap: 7px; }
.subtask-row { display: flex; align-items: center; gap: 9px; min-height: 52px; padding: 8px 11px; border: 1px solid var(--ib-border); border-radius: 12px; background: var(--ib-surface); }
.subtask-index { width: 24px; height: 24px; display: grid; flex: 0 0 auto; place-items: center; border-radius: 8px; color: var(--ib-primary); background: var(--ib-primary-soft); font-size: 9px; font-weight: 800; }
.subtask-row :deep(.v-selection-control) { min-height: 32px; }
.subtask-copy { flex: 1; min-width: 0; }
.subtask-copy > div { display: flex; align-items: center; gap: 7px; }
.subtask-copy strong { overflow-wrap: anywhere; color: var(--ib-text); font-size: 12px; }
.subtask-copy small { display: block; margin-top: 3px; color: var(--ib-text-muted); font-size: 9px; }
.delete-subtask-btn { flex: 0 0 auto; opacity: .72; }
.delete-subtask-btn:hover, .delete-subtask-btn:focus-visible { opacity: 1; background: color-mix(in srgb, var(--ib-danger) 8%, transparent); }
.add-first-subtask { width: 100%; display: flex; align-items: center; justify-content: center; gap: 7px; padding: 14px; border: 1px dashed var(--ib-border-strong); border-radius: 11px; color: var(--ib-primary); background: var(--ib-surface); cursor: pointer; font-size: 11px; transition: background .2s, border-color .2s; }
.add-first-subtask:hover { border-color: var(--ib-primary); background: var(--ib-surface); }
.task-empty { min-height: 370px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 40px; border: 1px dashed var(--ib-border); border-radius: 22px; color: var(--ib-text-muted); background: var(--ib-surface); text-align: center; }
.task-empty strong { color: var(--ib-text); font-size: 15px; }
.task-empty span { font-size: 11px; }
.type-selector { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 15px; }
.type-selector button { display: flex; align-items: flex-start; gap: 10px; padding: 14px; border: 1px solid var(--ib-border); border-radius: 13px; color: var(--ib-text-secondary); background: var(--ib-surface); cursor: pointer; text-align: left; }
.type-selector button.active { color: var(--ib-primary); border-color: var(--ib-primary); background: var(--ib-primary-soft); box-shadow: inset 0 0 0 1px var(--ib-primary); }
.type-selector span, .type-selector strong { display: block; }
.type-selector strong { font-size: 12px; }
.reminder-offsets-box { margin: 4px 0 16px; padding: 12px; border: 1px dashed var(--ib-border); border-radius: 10px; }
@media (max-width: 1050px) {
  .tasks-header, .tasks-header__side { align-items: flex-start; }
  .tasks-header { flex-direction: column; }
  .tasks-header__side { width: 100%; justify-content: space-between; }
  .task-filters { align-items: flex-start; flex-direction: column; gap: 8px; }
}
@media (max-width: 850px) {
  .tasks-page { padding: 24px 18px 100px; }
  .task-grid { grid-template-columns: 1fr; }
  .task-card--process { grid-column: auto; }
}
@media (max-width: 620px) {
  .tasks-page { padding-inline: 14px; }
  .tasks-header { padding: 21px 18px; border-radius: 21px; }
  .title-mark { width: 48px; height: 48px; border-radius: 15px; }
  .tasks-header__main { align-items: flex-start; }
  .tasks-header__side { flex-direction: column; }
  .task-overview, .header-actions { width: 100%; }
  .task-overview { justify-content: space-around; }
  .header-actions > .v-btn { flex: 1; }
  .filter-block { width: 100%; align-items: flex-start; flex-direction: column; gap: 4px; }
  .filter-label { padding: 0; border: 0; }
  .task-card { padding: 19px 16px; }
  .task-card__top { flex-wrap: wrap; }
  .task-card__actions { width: 100%; margin-left: 40px; justify-content: flex-end; }
  .task-meta, .progress-block, .subtask-section { margin-left: 0; }
  .subtask-row > .v-chip { display: none; }
  .type-selector { grid-template-columns: 1fr; }
}

/* Mono Workspace visual layer */
.tasks-page { min-height: calc(100vh - 60px); padding: 28px clamp(18px, 3vw, 44px) 72px; color: var(--ib-text); background: var(--ib-background); }
.tasks-page::before { display: none; }
.tasks-header { padding: 22px 24px; border-color: var(--ib-border); border-radius: var(--ib-radius-lg); background: var(--ib-surface); box-shadow: var(--ib-shadow-card); }
.tasks-header::after { display: none; }
.title-mark { border-radius: var(--ib-radius-md); background: var(--ib-primary); box-shadow: none; }
.eyebrow { color: var(--ib-primary-strong); }
.tasks-header h1,
.task-card__title h2,
.task-overview strong,
.task-empty strong { color: var(--ib-text); }
.tasks-header p,
.task-card__title p,
.task-meta,
.task-overview span,
.task-empty { color: var(--ib-text-secondary); }
.task-overview,
.task-filters,
.task-card,
.subtask-row,
.type-selector button,
.task-empty { border-color: var(--ib-border); background: var(--ib-surface) !important; box-shadow: var(--ib-shadow-card) !important; }
.task-filters { border-radius: var(--ib-radius-md); }
.filter-label { border-color: var(--ib-border); color: var(--ib-text-muted); }
.task-filters :deep(.v-chip) { color: var(--ib-text-secondary); }
.task-filters :deep(.filter-chip--selected) { color: var(--ib-primary-strong) !important; background: var(--ib-primary-soft) !important; }
.task-card { border-radius: var(--ib-radius-lg) !important; }
.task-card::before { height: 3px; background: var(--ib-primary); }
.task-card--process { border-color: var(--ib-border); }
.task-card--process::before { background: var(--ib-primary); }
.task-card:hover { border-color: var(--ib-border-strong); box-shadow: var(--ib-shadow-card) !important; }
.task-card--focused { border-color: var(--ib-primary) !important; box-shadow: 0 0 0 3px color-mix(in srgb, var(--ib-primary) 22%, transparent) !important; }
.task-meta span,
.progress-block { border-color: var(--ib-border); background: var(--ib-surface-subtle); }
.progress-block > div,
.subtask-copy small { color: var(--ib-text-secondary); }
.progress-block strong,
.subtask-heading,
.subtask-copy strong { color: var(--ib-text); }
.subtask-section { border-color: var(--ib-border); background: var(--ib-surface-subtle); }
.subtask-heading small,
.subtask-index { color: var(--ib-primary-strong); background: var(--ib-primary-soft); }
.add-first-subtask { border-color: var(--ib-border-strong); color: var(--ib-primary-strong); background: var(--ib-surface); }
.add-first-subtask:hover { border-color: var(--ib-primary); background: var(--ib-primary-soft); }
.type-selector button { color: var(--ib-text-secondary); }
.type-selector button.active { color: var(--ib-primary-strong); border-color: var(--ib-primary); background: var(--ib-primary-soft) !important; box-shadow: inset 0 0 0 1px var(--ib-primary) !important; }
.reminder-offsets-box { border-color: var(--ib-border-strong); }

/* 视图切换行 + deadlines Tab（合并自 DeadlinesView，token 化） */
.view-switch { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 22px; padding: 10px 14px; border: 1px solid var(--ib-border); border-radius: var(--ib-radius-md); background: var(--ib-surface); box-shadow: var(--ib-shadow-card); }
.view-switch :deep(.v-chip-group) { padding: 0; }
.view-switch :deep(.v-chip) { color: var(--ib-text-secondary); }
.view-switch :deep(.filter-chip--selected) { color: var(--ib-primary-strong) !important; background: var(--ib-primary-soft) !important; }
.urgent-toggle { flex: 0 0 auto; }
.task-filters { margin-top: 14px; }
.deadline-filters { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 14px 0; }
.deadline-filters :deep(.v-chip) { color: var(--ib-text-secondary); }
.deadline-filters :deep(.filter-chip--selected) { color: var(--ib-primary-strong) !important; background: var(--ib-primary-soft) !important; }
.deadline-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 20px; align-items: start; }
.deadline-list { display: flex; flex-direction: column; gap: 12px; }
.deadline-row { display: flex; align-items: center; gap: 12px; padding: 14px 16px; border: 1px solid var(--ib-border); border-radius: var(--ib-radius-md); background: var(--ib-surface); box-shadow: var(--ib-shadow-card); }
.deadline-row--overdue { border-color: color-mix(in srgb, var(--ib-danger) 35%, var(--ib-border)); }
.deadline-row--focused { border-color: var(--ib-primary) !important; box-shadow: 0 0 0 3px color-mix(in srgb, var(--ib-primary) 22%, transparent) !important; }
.deadline-copy { flex: 1; min-width: 0; }
.deadline-copy strong { display: block; overflow-wrap: anywhere; color: var(--ib-text); font-size: 14px; }
.deadline-copy small { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 4px; color: var(--ib-text-secondary); font-size: 11px; }
.deadline-copy small span { display: inline-flex; align-items: center; gap: 4px; }
.deadline-side { display: flex; flex: 0 0 auto; flex-direction: column; align-items: flex-end; gap: 6px; }
.deadline-date { color: var(--ib-primary-strong); font-size: 12px; font-weight: 600; }
.deadline-date.is-overdue { color: var(--ib-danger); }
.deadline-panel { padding: 14px 16px; border: 1px solid var(--ib-border); border-radius: var(--ib-radius-md); background: var(--ib-surface); box-shadow: var(--ib-shadow-card); }
.deadline-panel + .deadline-panel { margin-top: 16px; }
.deadline-panel__title { margin-bottom: 10px; color: var(--ib-text); font-size: 13px; font-weight: 700; }
.deadline-panel__list { display: flex; flex-direction: column; gap: 8px; }
.deadline-panel__row span { display: block; color: var(--ib-text); font-size: 12px; }
.deadline-panel__row small { color: var(--ib-text-secondary); font-size: 10px; }
.deadline-panel__empty { padding: 12px 0; color: var(--ib-text-muted); font-size: 11px; text-align: center; }
.deadline-panel__result { margin-top: 8px; color: var(--ib-text-secondary); font-size: 11px; }
@media (max-width: 1050px) {
  .deadline-layout { grid-template-columns: 1fr; }
}
@media (max-width: 620px) {
  .deadline-filters { align-items: flex-start; flex-direction: column; }
}
</style>
