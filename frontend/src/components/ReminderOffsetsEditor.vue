<template>
  <div class="offsets-editor">
    <div class="offsets-chips">
      <v-chip
        v-for="m in sortedModel"
        :key="m"
        size="small"
        color="primary"
        variant="tonal"
        closable
        :close-icon="'mdi-close'"
        @click:close="removeOffset(m)"
      >
        {{ offsetLabel(m) }}
      </v-chip>
      <span v-if="sortedModel.length === 0" class="offsets-empty">{{ $t('reminders.offsetsEmpty') }}</span>
    </div>

    <div class="offsets-quick">
      <v-chip
        v-for="m in quickPicks"
        :key="'q' + m"
        size="small"
        variant="outlined"
        :disabled="disabled || modelValue.includes(m) || modelValue.length >= maxCount"
        @click="addOffset(m)"
      >
        + {{ offsetLabel(m) }}
      </v-chip>
    </div>

    <div class="offsets-custom">
      <v-text-field
        v-model="customInput"
        type="number"
        min="1"
        max="10080"
        density="compact"
        variant="outlined"
        hide-details
        :placeholder="$t('reminders.offsetsCustomPlaceholder')"
        class="offsets-input"
        :disabled="disabled || modelValue.length >= maxCount"
        @keyup.enter="addCustom"
      />
      <v-btn
        size="small"
        variant="text"
        color="primary"
        :disabled="disabled || !canAddCustom"
        @click="addCustom"
      >
        {{ $t('reminders.offsetsAdd') }}
      </v-btn>
    </div>

    <div v-if="errorText" class="offsets-error">{{ errorText }}</div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

// 分钟偏移数组编辑器：契约 1–10080 分钟、最多 10 个、整数去重。
const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  maxCount: { type: Number, default: 10 },
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()

const MIN_OFFSET = 1
const MAX_OFFSET = 10080
const quickPicks = [5, 30, 60, 180, 720, 1440, 2880]

const customInput = ref('')
const errorText = ref('')

const sortedModel = computed(() => [...props.modelValue].sort((a, b) => a - b))

const customValue = computed(() => {
  const n = Number(customInput.value)
  return Number.isInteger(n) ? n : null
})
const canAddCustom = computed(() => {
  const n = customValue.value
  return (
    n != null &&
    n >= MIN_OFFSET &&
    n <= MAX_OFFSET &&
    !props.modelValue.includes(n) &&
    props.modelValue.length < props.maxCount
  )
})

function offsetLabel(m) {
  if (m % 1440 === 0) return t('reminders.offsetDays', { n: m / 1440 })
  if (m % 60 === 0) return t('reminders.offsetHours', { n: m / 60 })
  return t('reminders.offsetMinutes', { n: m })
}

function emitNext(next) {
  emit('update:modelValue', next)
}

function addOffset(m) {
  errorText.value = ''
  if (props.modelValue.includes(m)) return
  if (props.modelValue.length >= props.maxCount) {
    errorText.value = t('reminders.offsetsTooMany', { max: props.maxCount })
    return
  }
  emitNext([...props.modelValue, m])
}

function addCustom() {
  const n = customValue.value
  if (n == null || n < MIN_OFFSET || n > MAX_OFFSET) {
    errorText.value = t('reminders.offsetsRangeError')
    return
  }
  if (props.modelValue.includes(n)) {
    errorText.value = t('reminders.offsetsDuplicate')
    return
  }
  addOffset(n)
  if (!errorText.value) customInput.value = ''
}

function removeOffset(m) {
  errorText.value = ''
  emitNext(props.modelValue.filter((v) => v !== m))
}
</script>

<style scoped>
.offsets-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 420px;
}
.offsets-chips,
.offsets-quick {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.offsets-empty {
  color: #8c94a3;
  font-size: 12px;
}
.offsets-custom {
  display: flex;
  align-items: center;
  gap: 4px;
}
.offsets-input {
  max-width: 200px;
}
.offsets-error {
  color: #c04545;
  font-size: 12px;
}
</style>
