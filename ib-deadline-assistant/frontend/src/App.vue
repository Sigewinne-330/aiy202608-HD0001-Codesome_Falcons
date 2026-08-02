<template>
  <v-app>
    <!-- 导航抽屉 -->
    <v-navigation-drawer
      v-model="drawer"
      :rail="rail"
      permanent
      :width="220"
      :rail-width="64"
    >
      <v-list-item
        class="pa-3"
        prepend-icon="mdi-calendar-edit"
        :title="rail ? '' : '任务规划'"
        :subtitle="rail ? '' : '长期任务分阶段助手'"
        nav
      >
        <template v-slot:append>
          <v-btn
            :icon="rail ? 'mdi-chevron-right' : 'mdi-chevron-left'"
            variant="text"
            size="small"
            @click.stop="rail = !rail"
          />
        </template>
      </v-list-item>

      <v-divider />

      <v-list density="compact" nav>
        <v-list-item
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          :prepend-icon="item.icon"
          :title="rail ? '' : item.title"
          rounded="lg"
          class="mx-1 mb-1"
          color="primary"
        />
      </v-list>

      <template v-slot:append>
        <div class="pa-3" v-if="!rail">
          <v-divider class="mb-3" />
          <div class="text-caption text-grey mb-1">
            Demo 用户
          </div>
          <v-chip size="small" color="success" variant="tonal">
            <template v-slot:prepend>
              <v-icon size="16">mdi-circle-medium</v-icon>
            </template>
            在线
          </v-chip>
        </div>
      </template>
    </v-navigation-drawer>

    <!-- 主内容区 -->
    <v-main>
      <v-container fluid class="pa-6 h-100">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </v-container>
    </v-main>
  </v-app>
</template>

<script setup>
import { ref } from 'vue'

const drawer = ref(true)
const rail = ref(false)

const navItems = [
  { path: '/plan', title: '任务规划', icon: 'mdi-calendar-edit-outline' },
  { path: '/calendar', title: '日历', icon: 'mdi-calendar-month-outline' },
  { path: '/chat', title: 'AI 助手', icon: 'mdi-robot-outline' },
  { path: '/tasks', title: '任务管理', icon: 'mdi-clipboard-list-outline' },
  { path: '/deadlines', title: 'Deadline', icon: 'mdi-calendar-clock-outline' },
  { path: '/dashboard', title: '仪表盘', icon: 'mdi-view-dashboard-outline' },
]
</script>

<style>
/* 无需额外覆盖，让 Vuetify 原生处理布局 */
</style>
