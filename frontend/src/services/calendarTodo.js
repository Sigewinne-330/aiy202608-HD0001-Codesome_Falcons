export function createCalendarTodoForm(date) {
  return {
    task_type: 'todo',
    title: '',
    description: '',
    subject: '',
    priority: 'medium',
    deadline: date,
    deadline_time: '',
    reminder_mode: 'inherit',
    reminder_offsets: [5, 1440],
    estimated_hours: 0,
  }
}

export function buildCalendarTodoPayload(form) {
  const {
    deadline_time: deadlineTime,
    reminder_mode: reminderMode,
    reminder_offsets: reminderOffsets,
    ...base
  } = form
  const payload = { ...base, task_type: 'todo' }
  if (payload.deadline && deadlineTime) {
    payload.deadline = `${payload.deadline}T${deadlineTime}:00`
  }
  if (payload.deadline) {
    if (reminderMode === 'off') payload.reminder_offsets_minutes = []
    else if (reminderMode === 'custom') {
      payload.reminder_offsets_minutes = [...reminderOffsets].sort((a, b) => a - b)
    } else payload.reminder_offsets_minutes = null
  }
  return payload
}

export function isCalendarCellBlankClick(target) {
  if (!target || typeof target.closest !== 'function') return true
  return !target.closest('button, a, input, textarea, select, [role="button"]')
}
