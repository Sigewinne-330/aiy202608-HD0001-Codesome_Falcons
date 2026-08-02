<template>
  <div>
    <div class="d-flex align-center mb-4">
      <v-icon size="28" color="primary" class="mr-2">mdi-calendar-edit-outline</v-icon>
      <div>
        <div class="text-h6 font-weight-bold">任务规划</div>
        <div class="text-caption text-grey">输入任务信息和截止日期，自动生成分阶段执行计划</div>
      </div>
    </div>

    <v-row>
      <!-- 左侧：输入表单 -->
      <v-col cols="12" md="5">
        <v-card variant="outlined" class="mb-4">
          <v-card-title class="text-body-1 font-weight-bold">📝 任务信息</v-card-title>
          <v-card-text>
            <v-text-field
              v-model="form.title"
              label="任务名称"
              placeholder="例如：学习Python机器学习、准备雅思考试、完成产品设计项目"
              variant="outlined"
              density="comfortable"
              class="mb-3"
              hide-details
            />
            <v-row class="mb-3">
              <v-col cols="6">
                <v-text-field
                  v-model="form.word_count"
                  label="任务规模"
                  placeholder="5000"
                  type="number"
                  variant="outlined"
                  density="comfortable"
                  hide-details
                  suffix="单位"
                />
              </v-col>
              <v-col cols="6">
                <v-text-field
                  v-model="form.deadline"
                  label="截止日期"
                  type="date"
                  variant="outlined"
                  density="comfortable"
                  hide-details
                />
              </v-col>
            </v-row>
            <v-textarea
              v-model="form.description"
              label="补充说明（可选）"
              placeholder="例如：需要包含三个阶段、每周投入约10小时..."
              variant="outlined"
              density="comfortable"
              rows="2"
              hide-details
              class="mb-4"
            />
            <v-btn
              color="primary"
              block
              size="large"
              :loading="loading"
              :disabled="!form.title || !form.deadline"
              @click="generatePlan"
            >
              <v-icon left class="mr-1">mdi-magic-staff</v-icon>
              生成执行计划
            </v-btn>
          </v-card-text>
        </v-card>

        <!-- 概览卡片 -->
        <v-card v-if="plan" variant="outlined" color="primary">
          <v-card-text>
            <div class="text-caption text-grey mb-1">规划概览</div>
            <div class="d-flex align-center gap-4 flex-wrap">
              <div class="text-center">
                <div class="text-h5 font-weight-bold text-primary">{{ plan.phases.length }}</div>
                <div class="text-caption">执行阶段</div>
              </div>
              <v-divider vertical />
              <div class="text-center">
                <div class="text-h5 font-weight-bold text-primary">{{ plan.total_days }}</div>
                <div class="text-caption">总天数</div>
              </div>
              <v-divider vertical />
              <div class="text-center">
                <div class="text-h5 font-weight-bold text-primary">{{ plan.total_hours }}</div>
                <div class="text-caption">预估总小时</div>
              </div>
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <!-- 右侧：时间线计划 -->
      <v-col cols="12" md="7">
        <!-- 空状态 -->
        <v-sheet v-if="!plan && !loading" class="d-flex flex-column align-center justify-center pa-12" rounded="lg" border>
          <v-icon size="80" color="grey-lighten-1">mdi-timeline-text-outline</v-icon>
          <div class="text-h6 text-grey-darken-1 mt-4">还没有执行计划</div>
          <div class="text-body-2 text-grey mt-1 text-center" style="max-width: 360px;">
            在左侧输入你的任务信息，点击"生成执行计划"，
            系统会根据截止日期自动规划每个阶段的起止时间
          </div>
        </v-sheet>

        <!-- 加载中 -->
        <v-sheet v-if="loading" class="d-flex flex-column align-center justify-center pa-12" rounded="lg" border>
          <v-progress-circular indeterminate size="48" color="primary" class="mb-4" />
          <div class="text-body-1 text-grey-darken-1">正在规划执行时间线...</div>
          <div class="text-caption text-grey mt-1">根据截止日期倒推各阶段安排</div>
        </v-sheet>

        <!-- 时间线 -->
        <div v-if="plan && !loading">
          <div class="text-subtitle-1 font-weight-bold mb-3">
            📅 执行时间线
            <v-chip size="small" variant="tonal" color="primary" class="ml-2">
              {{ plan.deadline }} 截止
            </v-chip>
          </div>

          <v-timeline density="compact" side="end" line-color="primary" line-inset="8">
            <v-timeline-item
              v-for="(phase, i) in plan.phases"
              :key="i"
              :dot-color="phaseColor(phase.priority)"
              size="small"
              fill-dot
            >
              <v-card variant="outlined" class="mb-1">
                <v-card-item>
                  <template v-slot:prepend>
                    <v-avatar :color="phaseColor(phase.priority)" size="36">
                      <span class="text-white text-caption font-weight-bold">{{ i + 1 }}</span>
                    </v-avatar>
                  </template>

                  <v-card-title class="text-body-1 font-weight-bold">
                    {{ phase.phase }}
                    <v-chip
                      size="x-small"
                      :color="phaseColor(phase.priority)"
                      variant="tonal"
                      class="ml-2"
                    >
                      {{ priorityLabel(phase.priority) }}
                    </v-chip>
                  </v-card-title>

                  <v-card-subtitle>
                    <div class="d-flex align-center gap-2 text-caption text-grey">
                      <v-icon size="14">mdi-calendar-range</v-icon>
                      {{ formatDateRange(phase.start_date, phase.end_date) }}
                      <v-divider vertical class="mx-1" />
                      <v-icon size="14">mdi-clock-outline</v-icon>
                      {{ phase.estimated_hours }} 小时
                    </div>
                  </v-card-subtitle>
                </v-card-item>

                <v-card-text class="pt-0">
                  <div class="text-body-2">{{ phase.description }}</div>
                  <div class="mt-2 d-flex align-center gap-1">
                    <v-icon size="14" color="primary">mdi-package-variant-closed</v-icon>
                    <span class="text-caption font-weight-medium">交付物：</span>
                    <span class="text-caption">{{ phase.deliverables }}</span>
                  </div>
                </v-card-text>
              </v-card>
            </v-timeline-item>
          </v-timeline>

          <div v-if="plan" class="d-flex gap-2 mt-4">
            <v-btn color="primary" variant="tonal" prepend-icon="mdi-calendar-month" :to="calendarLink">
              在日历中查看
            </v-btn>
            <v-btn variant="outlined" prepend-icon="mdi-format-list-checks" to="/tasks">
              任务管理
            </v-btn>
          </div>
        </div>
      </v-col>
    </v-row>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const form = ref({
  title: '',
  word_count: 5000,
  deadline: '',
  description: '',
})

const plan = ref(null)
const loading = ref(false)

const API_BASE = '/api'

// 跳转到日历的链接（带上截止日期的月份）
const calendarLink = computed(() => {
  if (!plan.value?.deadline) return '/calendar'
  const parts = plan.value.deadline.split('-')
  return `/calendar?year=${parts[0]}&month=${parseInt(parts[1])}`
})

function phaseColor(priority) {
  return { low: 'grey', medium: 'primary', high: 'warning', urgent: 'error' }[priority] || 'primary'
}

function priorityLabel(priority) {
  return { low: '低', medium: '中', high: '高', urgent: '紧急' }[priority] || priority
}

function formatDateRange(start, end) {
  if (!start || !end) return ''
  const fmt = (d) => {
    const parts = d.split('-')
    return `${parseInt(parts[1])}/${parseInt(parts[2])}`
  }
  return `${fmt(start)} - ${fmt(end)}`
}

async function generatePlan() {
  if (!form.value.title || !form.value.deadline) return
  loading.value = true
  plan.value = null

  try {
    const res = await fetch(`${API_BASE}/tasks/plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: form.value.title,
        word_count: form.value.word_count || 0,
        deadline: form.value.deadline,
        description: form.value.description || '',
      }),
    })
    if (res.ok) {
      plan.value = await res.json()
    } else {
      const err = await res.json()
      console.error('Plan error:', err)
    }
  } catch (e) {
    console.error('Network error:', e)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.gap-1 { gap: 4px; }
.gap-2 { gap: 8px; }
.gap-4 { gap: 16px; }
</style>
