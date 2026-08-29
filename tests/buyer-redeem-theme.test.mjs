import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const component = await readFile('frontend/src/views/BuyerRedeem.vue', 'utf8')
const styles = await readFile('frontend/src/styles/buyer.css', 'utf8')

test('buyer redeem includes the approved decorative layers without adding interactions', () => {
  for (const className of ['buyer-stage-word', 'buyer-sticker', 'buyer-spark']) {
    assert.match(component, new RegExp(className))
  }
  assert.match(component, /aria-hidden="true"/)
  assert.match(styles, /pointer-events:\s*none/)
})

test('buyer theme carries the five accent colors and motion safeguards', () => {
  for (const color of ['#ff3af2', '#00f5d4', '#ffe600', '#ff6b35', '#7b2fff']) {
    assert.match(styles.toLowerCase(), new RegExp(color))
  }
  assert.match(styles, /@media\s*\(prefers-reduced-motion:\s*reduce\)/)
  assert.match(styles, /@media\s*\(max-width:\s*420px\)/)
})

test('buyer key icon is optically centered inside its circular badge', () => {
  assert.match(styles, /\.buyer-mark\s+\.anticon\s*\{[^}]*transform:\s*translate\(1px,\s*5px\);/s)
})

test('buyer challenge fits narrow mobile screens', () => {
  assert.match(styles, /\.buyer-turnstile-item\s+\.turnstile-widget\s*\{[^}]*width:\s*100%[^}]*max-width:\s*100%/s)
  assert.match(styles, /@media\s*\(max-width:\s*420px\)[\s\S]*\.buyer-shell\s*\{[^}]*padding:\s*24px 0[^}]*\}[\s\S]*\.buyer-tool\s*\{[^}]*width:\s*100%[^}]*padding:\s*24px 6px/s)
})
