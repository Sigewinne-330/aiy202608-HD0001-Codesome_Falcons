import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/stores/auth'
import i18n from '@/i18n'

const routes = [
  // ---- 项目介绍页（不需要登录，展示于注册/登录之前） ----
  {
    path: '/',
    name: 'Landing',
    component: () => import('../views/LandingView.vue'),
    meta: { titleKey: 'nav.landing', guest: true },
  },
  // ---- 认证页面（不需要登录） ----
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/LoginView.vue'),
    meta: { titleKey: 'nav.login', guest: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('../views/RegisterView.vue'),
    meta: { titleKey: 'nav.register', guest: true },
  },
  // ---- 需要登录的页面 ----
  {
    path: '/plan',
    name: 'Plan',
    component: () => import('../views/TaskPlanView.vue'),
    meta: { titleKey: 'nav.plan', icon: 'mdi-calendar-edit', requiresAuth: true },
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('../views/ChatView.vue'),
    meta: { titleKey: 'nav.chat', icon: 'mdi-robot', requiresAuth: true },
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('../views/TasksView.vue'),
    meta: { titleKey: 'nav.tasks', icon: 'mdi-clipboard-list', requiresAuth: true },
  },
  {
    path: '/deadlines',
    name: 'Deadlines',
    component: () => import('../views/DeadlinesView.vue'),
    meta: { titleKey: 'nav.deadlines', icon: 'mdi-calendar-clock', requiresAuth: true },
  },
  {
    path: '/calendar',
    name: 'Calendar',
    component: () => import('../views/CalendarView.vue'),
    meta: { titleKey: 'nav.calendar', icon: 'mdi-calendar-month', requiresAuth: true },
  },
  {
    path: '/urgent',
    name: 'Urgent',
    component: () => import('../views/UrgentView.vue'),
    meta: { titleKey: 'nav.urgent', icon: 'mdi-alert-outline', requiresAuth: true },
  },
  {
    path: '/progress',
    name: 'Progress',
    component: () => import('../views/ProgressView.vue'),
    meta: { titleKey: 'nav.progress', icon: 'mdi-chart-timeline-variant', requiresAuth: true },
  },
  {
    path: '/progress/:category',
    name: 'ProgressCategory',
    component: () => import('../views/ProgressView.vue'),
    meta: { titleKey: 'nav.progressCategory', icon: 'mdi-chart-timeline-variant', requiresAuth: true },
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('../views/DashboardView.vue'),
    meta: { titleKey: 'nav.dashboard', icon: 'mdi-view-dashboard', requiresAuth: true },
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
    return next({ path: '/calendar' })
  }

  next()
})

// 页面标题跟随语言
router.afterEach((to) => {
  const t = i18n.global.t
  document.title = to.meta.titleKey ? t(to.meta.titleKey) : 'IBuddy'
})

export default router
