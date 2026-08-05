<template>
  <div class="offsets-editor">
    <!-- 预设时点：点击即开关（参考系统日历的勾选交互，压缩为 chip 网格节省空间） -->
    <div class="offsets-presets">
      <button
        v-for="m in PRESETS"
        :key="m"
        type="button"
        class="offsets-preset"
        :class="{ 'offsets-preset--on': modelValue.includes(m) }"
        :disabled="disabled || (!modelValue.includes(m) && modelValue.length >= maxCount)"
        :aria-pressed="modelValue.includes(m)"
        @click="toggle(m)"
      >
        <v-icon v-if="modelValue.includes(m)" icon="mdi-check" size="13" />
        {{ offsetLabel(m) }}
      </button>

      <!-- 非预设的自定义值：以可删除 chip 形式并列展示 -->
      <span v-for="m in customValues" :key="'custom-' + m" class="offsets-preset offsets-preset--on offsets-preset--custom">
        <v-icon icon="mdi-tune-variant" size="12" />
        {{ offsetLabel(m) }}
        <button
          type="button"
          class="offsets-preset__remove"
          :disabled="disabled"
          :aria-label="$t('common.delete')"
          @click="removeOffset(m)"
        >
          ×
        </button>
      </span>
    </div>

    <!-- 自定义时长：天 / 时 / 分 三段输入，内部换算为分钟 -->
    <div class="offsets-custom">
      <div class="offsets-dur">
        <input
          v-model="customDays"
          type="number"
          min="0"
          max="7"
          class="offsets-dur__field"
          :disabled="disabled || modelValue.length >= maxCount"
          :aria-label="$t('reminders.offsetsUnitDays')"
          @keyup.enter="addCustom"
        />
        <span class="offsets-dur__unit">{{ $t('reminders.offsetsUnitDays') }}</span>
        <input
          v-model="customHours"
          type="number"
          min="0"
          max="23"
          class="offsets-dur__field"
          :disabled="disabled || modelValue.length >= maxCount"
          :aria-label="$t('reminders.offsetsUnitHours')"
          @keyup.enter="addCustom"
        />
        <span class="offsets-dur__unit">{{ $t('reminders.offsetsUnitHours') }}</span>
        <input
          v-model="customMinutes"
          type="number"
          min="0"
          max="59"
          class="offsets-dur__field"
          :disabled="disabled || modelValue.length >= maxCount"
          :aria-label="$t('reminders.offsetsUnitMinutes')"
          @keyup.enter="addCustom"
        />
        <span class="offsets-dur__unit">{{ $t('reminders.offsetsUnitMinutes') }}</span>
      </div>
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

// 分钟偏移编辑器：预设时点开关 + 自定义输入。契约 1–10080 分钟、最多 10 个、整数去重。
const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  maxCount: { type: Number, default: 10 },
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()

const MIN_OFFSET = 1
const MAX_OFFSET = 10080
// 预设时点：5分钟/15分钟/30分钟/1小时/2小时/1天/2天/7天
const PRESETS = [5, 15, 30, 60, 120, 1440, 2880, 10080]

const customDays = ref('')
const customHours = ref('')
const customMinutes = ref('')
const errorText = ref('')

// 已选但不在预设里的值（如历史数据 720 分钟），单独展示避免静默丢失
const customValues = computed(() =>
  props.modelValue.filter((m) => !PRESETS.includes(m)).sort((a, b) => a - b),
)

// 天/时/分 → 总分钟；空字段按 0 计；任意一段非整数则非法
const customTotal = computed(() => {
  const parts = [customDays.value, customHours.value, customMinutes.value]
  if (parts.every((p) => p === '' || p == null)) return null
  const nums = parts.map((p) => (p === '' || p == null ? 0 : Number(p)))
  if (nums.some((n) => !Number.isInteger(n) || n < 0)) return null
  const [d, h, m] = nums
  if (d > 7 || h > 23 || m > 59) return null
  return d * 1440 + h * 60 + m
})
const canAddCustom = computed(() => {
  const n = customTotal.value
  return (
    n != null &&
    n >= MIN_OFFSET &&
    n <= MAX_OFFSET &&
    !props.modelValue.includes(n) &&
    props.modelValue.length < props.maxCount
  )
})

function offsetLabel(m) {
  if (m % 1440 === 0) return t('reminders.offsetDays', { n: m / 1440 }, m / 1440)
  if (m % 60 === 0) return t('reminders.offsetHours', { n: m / 60 })
  return t('reminders.offsetMinutes', { n: m })
}

function emitNext(next) {
  emit('update:modelValue', next)
}

function toggle(m) {
  errorText.value = ''
  if (props.modelValue.includes(m)) {
    emitNext(props.modelValue.filter((v) => v !== m))
    return
  }
  if (props.modelValue.length >= props.maxCount) {
    errorText.value = t('reminders.offsetsTooMany', { max: props.maxCount })
    return
  }
  emitNext([...props.modelValue, m])
}

function addCustom() {
  const n = customTotal.value
  if (n == null || n < MIN_OFFSET || n > MAX_OFFSET) {
    errorText.value = t('reminders.offsetsRangeError')
    return
  }
  if (props.modelValue.includes(n)) {
    errorText.value = t('reminders.offsetsDuplicate')
    return
  }
  if (props.modelValue.length >= props.maxCount) {
    errorText.value = t('reminders.offsetsTooMany', { max: props.maxCount })
    return
  }
  emitNext([...props.modelValue, n])
  customDays.value = ''
  customHours.value = ''
  customMinutes.value = ''
  errorText.value = ''
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
.offsets-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
/* 预设开关：未选=描边，选中=实心打勾 */
.offsets-preset {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 11px;
  border: 1px solid #d5dbe6;
  border-radius: 999px;
  background: #fff;
  color: #5a6579;
  font-size: 12.5px;
  font-weight: 550;
  cursor: pointer;
  transition: background 0.14s ease, color 0.14s ease, border-color 0.14s ease;
}
.offsets-preset:hover:not(:disabled) {
  border-color: #9db8f0;
  color: #3567d6;
}
.offsets-preset--on,
.offsets-preset--on:hover:not(:disabled) {
  background: #3567d6;
  border-color: #3567d6;
  color: #fff;
}
.offsets-preset:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.offsets-preset--custom {
  cursor: default;
}
.offsets-preset__remove {
  border: 0;
  background: none;
  padding: 0 0 0 2px;
  font-size: 14px;
  line-height: 1;
  color: inherit;
  cursor: pointer;
}
.offsets-preset__remove:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.offsets-custom {
  display: flex;
  align-items: center;
  gap: 8px;
}
/* 天/时/分 三段输入 */
.offsets-dur {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border: 1px solid #d5dbe6;
  border-radius: 10px;
  background: #fff;
  transition: border-color 0.14s ease;
}
.offsets-dur:focus-within {
  border-color: #3567d6;
}
.offsets-dur__field {
  width: 40px;
  border: 0;
  outline: none;
  background: transparent;
  font-size: 15px;
  font-weight: 700;
  color: #232a3a;
  text-align: center;
  -moz-appearance: textfield;
  appearance: textfield;
}
.offsets-dur__field::-webkit-outer-spin-button,
.offsets-dur__field::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.offsets-dur__field:disabled {
  color: #9aa5b5;
}
.offsets-dur__unit {
  font-size: 12px;
  color: #8c94a3;
  margin-right: 6px;
}
.offsets-dur__unit:last-child {
  margin-right: 0;
}
.offsets-error {
  color: #c04545;
  font-size: 12px;
}
</style>
