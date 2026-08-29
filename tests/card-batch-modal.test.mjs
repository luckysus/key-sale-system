import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const app = readFileSync('frontend/src/views/AdminApp.vue', 'utf8')
const cards = readFileSync('frontend/src/views/CardManager.vue', 'utf8')
const batches = readFileSync('frontend/src/views/BatchManager.vue', 'utf8')

test('batch management is opened from card page instead of sidebar', () => {
  assert.doesNotMatch(app, /key="batches"/)
  assert.doesNotMatch(app, /BatchManager/)
  assert.match(cards, /生成卡密[\s\S]*批次管理/)
  assert.match(cards, /<BatchManager v-model:open="batchOpen"/)
})

test('batch management renders as a Qoder-style modal', () => {
  assert.match(batches, /<a-modal/)
  assert.match(batches, /title="卡密批次"/)
  assert.match(batches, /:footer="null"/)
  assert.match(batches, /size="small"/)
  assert.doesNotMatch(batches, /class="batch-page"/)
})
