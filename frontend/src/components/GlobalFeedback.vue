<template>
  <div class="feedback-stack" aria-live="polite" aria-atomic="false">
    <transition-group name="feedback">
      <v-alert
        v-for="notice in notices"
        :key="notice.id"
        class="feedback-notice"
        :type="notice.type"
        variant="flat"
        density="comfortable"
        closable
        @click:close="dismissNotice(notice.id)"
      >
        <div v-if="notice.title" class="feedback-notice__title">{{ notice.title }}</div>
        <div class="feedback-notice__body">{{ notice.message }}</div>
        <button
          v-if="notice.actionLabel && notice.action"
          class="feedback-notice__action"
          type="button"
          @click="runAction(notice)"
        >
          {{ notice.actionLabel }}
        </button>
      </v-alert>
    </transition-group>
  </div>
</template>

<script setup>
import { useFeedback } from '@/services/feedback'

const { notices, dismissNotice } = useFeedback()

function runAction(notice) {
  notice.action?.()
  dismissNotice(notice.id)
}
</script>

<style scoped>
.feedback-stack {
  position: fixed;
  z-index: 3000;
  top: 72px;
  right: 20px;
  display: grid;
  width: min(390px, calc(100vw - 32px));
  gap: 10px;
  pointer-events: none;
}

.feedback-notice {
  pointer-events: auto;
  border: 1px solid color-mix(in srgb, currentColor 18%, transparent);
  box-shadow: var(--ib-shadow-overlay);
}

.feedback-notice__title { margin-bottom: 2px; font-weight: 700; }
.feedback-notice__body { line-height: 1.45; }
.feedback-notice__action {
  margin-top: 8px;
  border: 0;
  background: transparent;
  color: inherit;
  font-weight: 700;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.feedback-enter-active,
.feedback-leave-active { transition: opacity var(--ib-duration-normal), transform var(--ib-duration-normal); }
.feedback-enter-from,
.feedback-leave-to { opacity: 0; transform: translateY(-8px); }

@media (max-width: 700px) {
  .feedback-stack { top: 66px; right: 16px; }
}
</style>
