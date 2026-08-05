import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/services/personalization.js', import.meta.url), 'utf8')
const pureSource = source
  .replace("import { api, authFetch } from '@/stores/auth'", 'const api = () => {}; const authFetch = () => {}')
  .replace('export const ', 'const ')
  .replaceAll('export function ', 'function ')
  .replace('export const personalizationApi', 'const personalizationApi')
const moduleUrl = `data:text/javascript;base64,${Buffer.from(`${pureSource}\nexport { normalizedConsentPayload, nextWorkControlState, parseServerTimestamp };`).toString('base64')}`
const { normalizedConsentPayload, nextWorkControlState, parseServerTimestamp } = await import(moduleUrl)

test('consent normalization cannot leave dependent processing enabled after withdrawal', () => {
  const payload = normalizedConsentPayload({
    operational_personalization_enabled: false,
    work_session_capture_enabled: true,
    llm_memory_enabled: true,
    cross_user_learning_enabled: true,
    near_tie_exploration_enabled: true,
    version: 3,
  })
  assert.equal(payload.operational_personalization_enabled, false)
  assert.equal(payload.work_session_capture_enabled, false)
  assert.equal(payload.llm_memory_enabled, false)
  assert.equal(payload.cross_user_learning_enabled, false)
  assert.equal(payload.near_tie_exploration_enabled, false)
  assert.equal(payload.expected_version, 3)
})

test('work controls reject invalid local transitions', () => {
  assert.equal(nextWorkControlState('idle', 'pause'), 'idle')
  assert.equal(nextWorkControlState('idle', 'start'), 'active')
  assert.equal(nextWorkControlState('active', 'pause'), 'paused')
  assert.equal(nextWorkControlState('paused', 'resume'), 'active')
  assert.equal(nextWorkControlState('paused', 'discard'), 'idle')
})

test('server timestamps without an offset are treated as UTC', () => {
  assert.equal(parseServerTimestamp('2026-08-05T11:50:00'), Date.parse('2026-08-05T11:50:00Z'))
  assert.equal(parseServerTimestamp('2026-08-05T11:50:00+08:00'), Date.parse('2026-08-05T03:50:00Z'))
})
