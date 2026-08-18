import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/services/managebac.js', import.meta.url), 'utf8')
const testableSource = source.replace(
  "import { api, ApiError } from '@/stores/auth'",
  'class ApiError extends Error {}; const calls = []; const api = (...args) => { calls.push(args); return args }',
)
const moduleUrl = `data:text/javascript;base64,${Buffer.from(`${testableSource}\nexport { calls as __calls };`).toString('base64')}`
const {
  __calls,
  createDisconnectedManageBacState,
  isManageBacFeedCandidate,
  managebacApi,
  normalizeManageBacConnection,
} = await import(moduleUrl)

const [en, zhCN, zhTW] = await Promise.all([
  import('../src/locales/en.js'),
  import('../src/locales/zh-CN.js'),
  import('../src/locales/zh-TW.js'),
])

function keyShape(value, prefix = '') {
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return child && typeof child === 'object' ? keyShape(child, path) : [path]
  }).sort()
}

test('feed candidate accepts subscription protocols but rejects insecure HTTP', () => {
  assert.equal(isManageBacFeedCandidate(' webcal://school.managebac.com/student/events/token.ics '), true)
  assert.equal(isManageBacFeedCandidate('https://school.managebac.com/student/events/token.ics'), true)
  assert.equal(isManageBacFeedCandidate('http://school.managebac.com/student/events/token.ics'), false)
  assert.equal(isManageBacFeedCandidate(''), false)
})

test('connection normalization has deterministic connected and disconnected states', () => {
  assert.deepEqual(createDisconnectedManageBacState(15), {
    connected: false,
    enabled: false,
    status: null,
    sync_interval_minutes: 15,
  })
  assert.deepEqual(normalizeManageBacConnection(null, 20), {
    connected: false,
    enabled: false,
    status: null,
    sync_interval_minutes: 20,
  })
  const active = normalizeManageBacConnection({ connected: true, enabled: 1, status: 'active' })
  assert.equal(active.connected, true)
  assert.equal(active.enabled, true)
  assert.equal(active.status, 'active')
})

test('API wrapper uses the authenticated ManageBac endpoints and never places a feed URL in a query string', () => {
  const feed = 'webcal://school.managebac.com/student/events/private-token.ics'
  managebacApi.status()
  managebacApi.validate(feed)
  managebacApi.connect(feed)
  managebacApi.sync()
  managebacApi.setEnabled(false)
  managebacApi.runs(7)
  managebacApi.disconnect(true)

  assert.deepEqual(__calls.map(([path]) => path), [
    '/api/integrations/managebac/status',
    '/api/integrations/managebac/validate',
    '/api/integrations/managebac/connect',
    '/api/integrations/managebac/sync',
    '/api/integrations/managebac/settings',
    '/api/integrations/managebac/runs?limit=7',
    '/api/integrations/managebac/disconnect?delete_imported_tasks=true',
  ])
  assert.equal(__calls[1][1].body, JSON.stringify({ feed_url: feed }))
  assert.equal(__calls[2][1].body, JSON.stringify({ feed_url: feed }))
  assert.equal(__calls.some(([path]) => path.includes('private-token')), false)
})

test('ManageBac translations have the same complete key shape in all three locales', () => {
  const expected = keyShape(en.default.managebac)
  assert.deepEqual(keyShape(zhCN.default.managebac), expected)
  assert.deepEqual(keyShape(zhTW.default.managebac), expected)
})
