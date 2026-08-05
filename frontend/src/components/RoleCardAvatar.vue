<template>
  <v-avatar
    :size="size"
    :color="avatarUrl ? 'grey-lighten-4' : color"
    :class="['role-card-avatar', { 'role-card-avatar--image': avatarUrl }]"
    :title="resolvedTitle || undefined"
  >
    <img
      v-if="avatarUrl"
      :src="avatarUrl"
      :alt="resolvedTitle || 'AI role avatar'"
      class="role-card-avatar__image"
    />
    <v-icon v-else :icon="fallbackIcon" color="white" :size="iconSize" />
  </v-avatar>
</template>

<script setup>
import { computed } from 'vue'
import { roleCardAvatarUrl, roleCardIcon, roleCardName } from '@/services/roleCardVisuals'

const props = defineProps({
  slug: { type: String, default: '' },
  title: { type: String, default: '' },
  size: { type: [Number, String], default: 32 },
  iconSize: { type: [Number, String], default: 18 },
  color: { type: String, default: 'primary' },
  icon: { type: String, default: '' },
})

const avatarUrl = computed(() => roleCardAvatarUrl(props.slug))
const fallbackIcon = computed(() => props.icon || roleCardIcon(props.slug))
const resolvedTitle = computed(() => props.title || roleCardName(props.slug))
</script>

<style scoped>
.role-card-avatar {
  flex: 0 0 auto;
}

.role-card-avatar--image {
  border: 1px solid rgba(37, 56, 101, 0.12);
  background: #fff;
}

.role-card-avatar__image {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
  object-position: center top;
}
</style>
