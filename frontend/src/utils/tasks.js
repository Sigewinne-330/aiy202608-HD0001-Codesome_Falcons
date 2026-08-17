export const PRIORITY_ORDER = Object.freeze({ urgent: 4, high: 3, medium: 2, low: 1 })

export function priorityWeight(priority) {
  return PRIORITY_ORDER[priority] || 0
}

export function priorityColor(priority) {
  return { urgent: 'error', high: 'warning', medium: 'primary', low: 'success' }[priority] || 'primary'
}

export function isTaskDone(task) {
  return ['done', 'completed'].includes(task?.status)
}

export function flattenTasks(nodes, output = []) {
  for (const item of nodes || []) {
    output.push(item)
    flattenTasks(item.subtasks, output)
  }
  return output
}

export function daysUntil(value, from = new Date()) {
  if (!value) return Number.POSITIVE_INFINITY
  const start = new Date(from)
  start.setHours(0, 0, 0, 0)
  const date = new Date(`${value}T00:00:00`)
  return Math.round((date - start) / 86400000)
}

export function taskRisk(item, from = new Date()) {
  if (isTaskDone(item)) return 0
  if (!item?.deadline) return 25
  const days = daysUntil(item.deadline, from)
  let base = 18
  if (days < 0) base = 100
  else if (days <= 3) base = 88
  else if (days <= 7) base = 72
  else if (days <= 14) base = 52
  else if (days <= 30) base = 32
  const statusFactor = item.status === 'in_progress' ? 0.72 : 1
  const priorityFactor = { low: 0.75, medium: 0.9, high: 1.05, urgent: 1.18 }[item.priority] || 0.9
  return Math.min(100, Math.round(base * statusFactor * priorityFactor))
}

export function aggregateRisk(items) {
  const scores = (items || []).filter((item) => !isTaskDone(item)).map((item) => taskRisk(item))
  if (!scores.length) return 0
  const average = scores.reduce((sum, value) => sum + value, 0) / scores.length
  return Math.round(Math.max(...scores) * 0.6 + average * 0.4)
}
