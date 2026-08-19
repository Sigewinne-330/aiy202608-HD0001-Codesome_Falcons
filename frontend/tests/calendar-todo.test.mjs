import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildCalendarTodoPayload,
  createCalendarTodoForm,
  isCalendarCellBlankClick,
} from '../src/services/calendarTodo.js'

test('calendar click creates a todo form on the clicked date', () => {
  const form = createCalendarTodoForm('2026-08-21')
  assert.equal(form.task_type, 'todo')
  assert.equal(form.deadline, '2026-08-21')
  assert.equal(form.reminder_mode, 'inherit')
})

test('calendar todo payload is always todo and combines optional time', () => {
  const form = {
    ...createCalendarTodoForm('2026-08-21'),
    task_type: 'process',
    title: 'Read chapter',
    deadline_time: '16:30',
    reminder_mode: 'custom',
    reminder_offsets: [1440, 5],
  }
  const payload = buildCalendarTodoPayload(form)
  assert.equal(payload.task_type, 'todo')
  assert.equal(payload.deadline, '2026-08-21T16:30:00')
  assert.deepEqual(payload.reminder_offsets_minutes, [5, 1440])
  assert.equal('deadline_time' in payload, false)
  assert.equal('reminder_mode' in payload, false)
})

test('calendar cell ignores clicks originating from existing interactive items', () => {
  assert.equal(isCalendarCellBlankClick({ closest: () => null }), true)
  assert.equal(isCalendarCellBlankClick({ closest: () => ({ tagName: 'BUTTON' }) }), false)
})
