export const TASKS_CHANGED_EVENT = 'ibuddy:tasks-changed'

export function notifyTasksChanged() {
  window.dispatchEvent(new CustomEvent(TASKS_CHANGED_EVENT))
}

export function onTasksChanged(handler) {
  window.addEventListener(TASKS_CHANGED_EVENT, handler)
  return () => window.removeEventListener(TASKS_CHANGED_EVENT, handler)
}
