import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import ts from "typescript";

async function loadFormatter() {
  const path = resolve("frontend/src/utils/cardDelivery.ts");
  assert.ok(existsSync(path), "card delivery formatter is missing");
  const source = readFileSync(path, "utf8");
  const javascript = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);
}

test("formats one card with code, redeem URL, and converter URL in order", async () => {
  const { formatCardDeliveryInfo } = await loadFormatter();

  assert.equal(
    formatCardDeliveryInfo(["SA6Z-UQ54-TWUV-SRY5"]),
    [
      "卡密：SA6Z-UQ54-TWUV-SRY5",
      "卡密提取网址：https://buyer.example.com/",
      "格式转换网站：https://converter.example.com/",
    ].join("\n"),
  );
});

test("separates multiple card delivery blocks with one blank line", async () => {
  const { formatCardDeliveryInfo } = await loadFormatter();

  assert.equal(
    formatCardDeliveryInfo(["CARD-ONE", "CARD-TWO"]),
    [
      "卡密：CARD-ONE",
      "卡密提取网址：https://buyer.example.com/",
      "格式转换网站：https://converter.example.com/",
      "",
      "卡密：CARD-TWO",
      "卡密提取网址：https://buyer.example.com/",
      "格式转换网站：https://converter.example.com/",
    ].join("\n"),
  );
});
