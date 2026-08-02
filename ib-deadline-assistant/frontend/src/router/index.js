import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/plan',
  },
  {
    path: '/plan',
    name: 'Plan',
    component: () => import('../views/TaskPlanView.vue'),
    meta: { title: '任务规划', icon: 'mdi-calendar-edit' },
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('../views/ChatView.vue'),
    meta: { title: 'AI 助手', icon: 'mdi-robot' },
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('../views/TasksView.vue'),
    meta: { title: '任务管理', icon: 'mdi-clipboard-list' },
  },
  {
    path: '/deadlines',
    name: 'Deadlines',
    component: () => import('../views/DeadlinesView.vue'),
    meta: { title: 'Deadline', icon: 'mdi-calendar-clock' },
  },
  {
    path: '/calendar',
    name: 'Calendar',
    component: () => import('../views/CalendarView.vue'),
    meta: { title: '日历', icon: 'mdi-calendar-month' },
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('../views/DashboardView.vue'),
    meta: { title: '仪表盘', icon: 'mdi-view-dashboard' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
