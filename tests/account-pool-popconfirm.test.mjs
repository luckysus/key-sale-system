import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const accountPool = readFileSync("frontend/src/views/AccountPool.vue", "utf8");
const confirmHelper = readFileSync("frontend/src/utils/confirm.ts", "utf8");

test("account extraction confirmation uses the shared centered danger modal", () => {
  assert.match(accountPool, /confirmDanger\(\{/);
  assert.doesNotMatch(accountPool, /<a-popconfirm/);
  assert.match(confirmHelper, /Modal\.confirm\(\{/);
  assert.match(confirmHelper, /centered:\s*true/);
  assert.match(confirmHelper, /okType:\s*'danger'/);
});
