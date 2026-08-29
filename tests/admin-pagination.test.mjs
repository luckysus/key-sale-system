import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const files = [
  'frontend/src/views/CardManager.vue',
  'frontend/src/views/AccountPool.vue',
  'frontend/src/views/BatchManager.vue',
  'frontend/src/views/ExtractionLogs.vue',
]

test('every admin table with a page-size selector controls and updates pagination state', () => {
  for (const file of files) {
    const source = readFileSync(file, 'utf8')
    assert.match(source, /const tablePagination = reactive\(\{[\s\S]*?current:\s*1,[\s\S]*?pageSize:/, `${file} must use reactive pagination`)
    assert.match(source, /<a-table[\s\S]*?:pagination="tablePagination"[\s\S]*?@change="onTableChange"/, `${file} must handle table changes`)
    assert.match(source, /function onTableChange\(pagination:[\s\S]*?tablePagination\.current = pagination\.current[\s\S]*?tablePagination\.pageSize = pagination\.pageSize/, `${file} must persist page and page-size changes`)
  }
})
