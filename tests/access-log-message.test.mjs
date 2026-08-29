import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import ts from "typescript";

async function loadClientHelpers() {
  const source = readFileSync(resolve("frontend/src/api/client.ts"), "utf8");
  const javascript = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);
}

test("translates historical English account-count logs to Chinese", async () => {
  const { accessLogMessageText } = await loadClientHelpers();

  assert.equal(accessLogMessageText({ result: "success", message: "1 accounts" }), "1 个账号");
  assert.equal(accessLogMessageText({ result: "success", message: "12 accounts" }), "12 个账号");
});

test("labels redemption protection outcomes for administrators", async () => {
  const { accessLogResultText } = await loadClientHelpers();

  assert.equal(accessLogResultText("timeout"), "处理超时");
  assert.equal(accessLogResultText("busy"), "处理中");
});
