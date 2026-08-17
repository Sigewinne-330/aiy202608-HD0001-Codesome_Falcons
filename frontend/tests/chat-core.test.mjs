import assert from 'node:assert/strict'
import test from 'node:test'
import {
  consumeChatStream,
  estimateTokens,
  extractTaskPayload,
  tokensToCredits,
} from '../src/services/chatCore.js'

test('extractTaskPayload accepts only a trailing task payload', () => {
  const content = 'Plan ready.\n```json\n{"title":"EE draft","subtasks":[]}\n```'
  assert.deepEqual(extractTaskPayload(content), { title: 'EE draft', subtasks: [] })
  assert.equal(extractTaskPayload('```json\n{"title":"missing subtasks"}\n```'), null)
  assert.equal(extractTaskPayload('not json'), null)
})

test('credit estimation handles Latin and CJK text consistently', () => {
  assert.equal(estimateTokens('abcd'), 1)
  assert.equal(estimateTokens('中文'), 2)
  assert.equal(tokensToCredits(0), 0)
  assert.equal(tokensToCredits(1001), 2)
})

test('consumeChatStream handles fragmented SSE data and a final unterminated event', async () => {
  const encoder = new TextEncoder()
  const response = new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('data: "Hel'))
      controller.enqueue(encoder.encode('lo"\n\ndata: {"done":true,"tokens":1200,'))
      controller.enqueue(encoder.encode('"credits":2}\n\ndata: "!"'))
      controller.close()
    },
  }))
  const chunks = []
  let usage = null
  await consumeChatStream(response, {
    onChunk: (chunk) => chunks.push(chunk),
    onUsage: (value) => { usage = value },
  })
  assert.equal(chunks.join(''), 'Hello!')
  assert.equal(usage.credits, 2)
})
