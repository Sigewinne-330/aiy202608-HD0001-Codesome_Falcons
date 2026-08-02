<template>
  <v-app>
    <!-- 导航抽屉（仅登录后显示） -->
    <v-navigation-drawer
      v-if="isAuthenticated"
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
        <div class="px-3 pb-3" v-if="!rail">
          <v-divider class="mb-3" />
          <div class="d-flex align-center">
            <v-avatar size="36" color="primary" class="mr-2">
              <span class="text-white text-body-2">{{ userInitial }}</span>
            </v-avatar>
            <div style="flex:1; min-width:0;">
              <div class="text-body-2 font-weight-medium text-truncate">
                {{ user?.username || '用户' }}
              </div>
              <v-chip size="x-small" color="success" variant="tonal">
                <template v-slot:prepend>
                  <v-icon size="12">mdi-circle-medium</v-icon>
                </template>
                在线
              </v-chip>
            </div>
            <v-btn
              icon="mdi-logout"
              size="small"
              variant="text"
              @click="handleLogout"
            />
          </div>
        </div>
      </template>
    </v-navigation-drawer>

    <!-- 主内容区 -->
    <v-main>
      <!-- 登录页面全屏无侧栏 -->
      <router-view v-if="!isAuthenticated" v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
      <!-- 已登录内容 -->
      <v-container v-else fluid class="pa-6 h-100">
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
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'

const router = useRouter()
const { user, isAuthenticated, logout, restoreSession } = useAuth()

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

const userInitial = computed(() => {
  const name = user.value?.username || ''
  return name.charAt(0).toUpperCase()
})

function handleLogout() {
  logout()
  router.push('/login')
}

// 启动时恢复会话
onMounted(async () => {
  await restoreSession()
})
</script>

<style>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
