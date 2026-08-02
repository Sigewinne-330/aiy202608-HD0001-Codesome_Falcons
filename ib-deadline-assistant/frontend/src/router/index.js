import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/stores/auth'

const routes = [
  {
    path: '/',
    redirect: '/plan',
  },
  // ---- 认证页面（不需要登录） ----
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/LoginView.vue'),
    meta: { title: '登录', guest: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('../views/RegisterView.vue'),
    meta: { title: '注册', guest: true },
  },
  // ---- 需要登录的页面 ----
  {
    path: '/plan',
    name: 'Plan',
    component: () => import('../views/TaskPlanView.vue'),
    meta: { title: '任务规划', icon: 'mdi-calendar-edit', requiresAuth: true },
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('../views/ChatView.vue'),
    meta: { title: 'AI 助手', icon: 'mdi-robot', requiresAuth: true },
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('../views/TasksView.vue'),
    meta: { title: '任务管理', icon: 'mdi-clipboard-list', requiresAuth: true },
  },
  {
    path: '/deadlines',
    name: 'Deadlines',
    component: () => import('../views/DeadlinesView.vue'),
    meta: { title: 'Deadline', icon: 'mdi-calendar-clock', requiresAuth: true },
  },
  {
    path: '/calendar',
    name: 'Calendar',
    component: () => import('../views/CalendarView.vue'),
    meta: { title: '日历', icon: 'mdi-calendar-month', requiresAuth: true },
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('../views/DashboardView.vue'),
    meta: { title: '仪表盘', icon: 'mdi-view-dashboard', requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// ---- 全局路由守卫 ----
router.beforeEach((to, from, next) => {
  const { isAuthenticated } = useAuth()

  // 访问需要登录的页面但未认证 → 跳转登录
  if (to.meta.requiresAuth && !isAuthenticated.value) {
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }

  // 已登录用户访问登录/注册页 → 跳转到首页
  if (to.meta.guest && isAuthenticated.value) {
    return next({ path: '/plan' })
  }

  next()
})

export default router
