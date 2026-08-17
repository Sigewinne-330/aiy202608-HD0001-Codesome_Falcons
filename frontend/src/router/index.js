import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/stores/auth'
import i18n from '@/i18n'
import { safeInternalRedirect } from '@/utils/navigation'

const routes = [
  // ---- 项目介绍页（所有人进入网站的第一个界面，已登录用户也停留在此） ----
  {
    path: '/',
    name: 'Landing',
    component: () => import('../views/LandingView.vue'),
    meta: { titleKey: 'nav.landing', guest: true, guestRedirect: false },
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
    path: '/calendar',
    name: 'Calendar',
    component: () => import('../views/CalendarView.vue'),
    meta: { titleKey: 'nav.calendar', requiresAuth: true },
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('../views/TasksView.vue'),
    meta: { titleKey: 'nav.tasks', requiresAuth: true },
  },
  // 兼容旧入口：重定向到任务页对应视图（保留原有 query，如 ?focus=）
  {
    path: '/deadlines',
    redirect: (to) => ({ path: '/tasks', query: { ...to.query, tab: 'deadlines' } }),
  },
  {
    path: '/urgent',
    redirect: (to) => ({ path: '/tasks', query: { ...to.query, filter: 'urgent' } }),
  },
  {
    path: '/progress',
    name: 'Progress',
    component: () => import('../views/ProgressView.vue'),
    meta: { titleKey: 'nav.progress', requiresAuth: true },
  },
  {
    path: '/progress/:category',
    name: 'ProgressCategory',
    component: () => import('../views/ProgressView.vue'),
    meta: { titleKey: 'nav.progressCategory', requiresAuth: true },
  },
  {
    path: '/progress/:category/:taskId',
    name: 'ProgressTimeline',
    component: () => import('../views/ProgressView.vue'),
    meta: { titleKey: 'nav.progressCategory', requiresAuth: true },
  },
  {
    path: '/billing',
    name: 'Billing',
    component: () => import('../views/BillingView.vue'),
    meta: { titleKey: 'billing.title', requiresAuth: true },
  },
  {
    path: '/reminders',
    name: 'Reminders',
    component: () => import('../views/RemindersView.vue'),
    meta: { titleKey: 'reminders.title', requiresAuth: true },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
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

  // 已登录用户访问登录/注册页 → 跳转到首页（Landing 例外：所有人都先看介绍页）
  if (to.meta.guest && to.meta.guestRedirect !== false && isAuthenticated.value) {
    return next(safeInternalRedirect(to.query.redirect, '/calendar'))
  }

  next()
})

// 页面标题跟随语言
router.afterEach((to) => {
  const t = i18n.global.t
  document.title = to.meta.titleKey ? t(to.meta.titleKey) : 'IBuddy'
})

export default router
