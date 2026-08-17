import assert from 'node:assert/strict'
import test from 'node:test'
import { redesignMessages } from '../src/locales/redesign.js'
import { progressMessages } from '../src/locales/progress.js'
import en from '../src/locales/en.js'
import zhCN from '../src/locales/zh-CN.js'
import zhTW from '../src/locales/zh-TW.js'

function leafKeys(value, prefix = '') {
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return child && typeof child === 'object' && !Array.isArray(child)
      ? leafKeys(child, path)
      : [path]
  }).sort()
}

for (const [name, messages] of [['redesign', redesignMessages], ['progress', progressMessages]]) {
  test(`${name} locale extensions have matching keys`, () => {
    const baseline = leafKeys(messages.en)
    assert.deepEqual(leafKeys(messages['zh-CN']), baseline)
    assert.deepEqual(leafKeys(messages['zh-TW']), baseline)
  })
}

test('base locales have matching keys', () => {
  const baseline = leafKeys(en)
  assert.deepEqual(leafKeys(zhCN), baseline)
  assert.deepEqual(leafKeys(zhTW), baseline)
})
