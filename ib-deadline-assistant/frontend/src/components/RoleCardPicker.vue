<template>
  <v-dialog :model-value="modelValue" max-width="640" scrollable @update:model-value="close">
    <v-card rounded="xl">
      <v-card-title class="d-flex align-center pt-5 px-6">
        <span>{{ $t('reminders.roleCardPickerTitle') }}</span>
        <v-spacer />
        <v-btn icon="mdi-close" variant="text" size="small" :aria-label="$t('common.close')" @click="close" />
      </v-card-title>

      <v-card-text class="px-6 pb-2">
        <!-- 恢复默认 -->
        <div
          class="role-card role-card--default"
          :class="{ 'role-card--selected': internalSelected == null }"
          role="radio"
          :aria-checked="internalSelected == null"
          tabindex="0"
          @click="internalSelected = null"
          @keydown.enter.space.prevent="internalSelected = null"
        >
          <v-icon icon="mdi-star-circle-outline" color="primary" class="mr-3" />
          <div class="role-card__copy">
            <div class="role-card__name">{{ $t('reminders.roleCardDefault') }}</div>
            <div class="role-card__desc">{{ $t('reminders.roleCardDefaultHelp') }}</div>
          </div>
          <v-icon v-if="internalSelected == null" icon="mdi-check-circle" color="primary" />
        </div>

        <!-- 角色卡列表 -->
        <div
          v-for="card in cards"
          :key="card.id"
          class="role-card"
          :class="{ 'role-card--selected': internalSelected === card.id }"
          role="radio"
          :aria-checked="internalSelected === card.id"
          tabindex="0"
          @click="internalSelected = card.id"
          @keydown.enter.space.prevent="internalSelected = card.id"
        >
          <v-icon :icon="cardIcon(card.slug)" color="primary" class="mr-3" />
          <div class="role-card__copy">
            <div class="role-card__name" v-text="card.name" />
            <div class="role-card__desc" v-text="card.description" />

            <!-- 按需展开的示例详情（全部纯文本） -->
            <v-btn
              size="x-small"
              variant="text"
              color="primary"
              class="px-0 mt-1"
              :loading="detailLoadingId === card.id"
              @click.stop="toggleDetail(card)"
            >
              {{ expandedId === card.id ? $t('reminders.hideExample') : $t('reminders.viewExample') }}
            </v-btn>
            <div v-if="expandedId === card.id && detail" class="role-card__detail">
              <div v-if="detail.personality" class="detail-row">
                <span class="detail-label">{{ $t('reminders.personality') }}</span>
                <span v-text="detail.personality" />
              </div>
              <div v-if="detail.speaking_style" class="detail-row">
                <span class="detail-label">{{ $t('reminders.speakingStyle') }}</span>
                <span v-text="detail.speaking_style" />
              </div>
              <template v-if="exampleMessages.length">
                <div class="detail-label mt-2">{{ $t('reminders.exampleMessages') }}</div>
                <div
                  v-for="(msg, idx) in exampleMessages"
                  :key="idx"
                  class="example-message"
                  v-text="msg"
                />
              </template>
            </div>
          </div>
          <v-icon v-if="internalSelected === card.id" icon="mdi-check-circle" color="primary" />
        </div>
      </v-card-text>

      <v-card-actions class="px-6 pb-5">
        <v-spacer />
        <v-btn variant="text" @click="close">{{ $t('common.cancel') }}</v-btn>
        <v-btn color="primary" @click="confirm">{{ $t('common.confirm') }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { getRoleCard, ApiError } from '@/services/reminders'

const props = defineProps({
  modelValue: Boolean,
  cards: { type: Array, default: () => [] },
  selectedId: { type: [Number, String], default: null },
})
const emit = defineEmits(['update:modelValue', 'select', 'unauthorized'])

const internalSelected = ref(props.selectedId)
const expandedId = ref(null)
const detail = ref(null)
const detailLoadingId = ref(null)

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      internalSelected.value = props.selectedId
      expandedId.value = null
      detail.value = null
    }
  },
)

const exampleMessages = computed(() => {
  const msgs = detail.value?.example_messages
  return Array.isArray(msgs) ? msgs : []
})

function cardIcon(slug) {
  const map = {
    'friendly-warm-guy': 'mdi-account-heart-outline',
    'tech-geek': 'mdi-laptop',
    'sweet-high-school-girl': 'mdi-flower-outline',
  }
  return map[slug] || 'mdi-account-star-outline'
}

async function toggleDetail(card) {
  if (expandedId.value === card.id) {
    expandedId.value = null
    detail.value = null
    return
  }
  expandedId.value = card.id
  detail.value = null
  detailLoadingId.value = card.id
  try {
    detail.value = await getRoleCard(card.id)
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      emit('unauthorized')
      return
    }
    expandedId.value = null
  } finally {
    detailLoadingId.value = null
  }
}

function close() {
  emit('update:modelValue', false)
}

function confirm() {
  // null 表示恢复默认角色卡
  emit('select', internalSelected.value)
  close()
}
</script>

<style scoped>
.role-card {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  padding: 14px 16px;
  margin-bottom: 10px;
  border: 1px solid #e3e6ec;
  border-radius: 14px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.role-card:hover {
  background: #f7f8fb;
}
.role-card--selected {
  border-color: rgb(var(--v-theme-primary));
  background: rgba(var(--v-theme-primary), 0.05);
}
.role-card__copy {
  flex: 1;
  min-width: 0;
}
.role-card__name {
  font-weight: 600;
  color: #232a3a;
  font-size: 14px;
}
.role-card__desc {
  color: #77808f;
  font-size: 12px;
  margin-top: 2px;
}
.role-card__detail {
  margin-top: 8px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f4f6fa;
  font-size: 12px;
  color: #4a5262;
}
.detail-row {
  margin-bottom: 6px;
}
.detail-label {
  font-weight: 600;
  margin-right: 8px;
  color: #39415a;
}
.example-message {
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #e6e9f0;
  white-space: pre-wrap;
}
</style>
