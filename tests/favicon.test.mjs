import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

test("frontend declares the neon key favicon", () => {
  const html = readFileSync("frontend/index.html", "utf8");
  const faviconPath = "frontend/public/favicon.svg";

  assert.match(html, /<link\s+rel="icon"\s+type="image\/svg\+xml"\s+href="\/favicon\.svg"\s*\/>/);
  assert.ok(existsSync(faviconPath), "favicon asset is missing");

  const favicon = readFileSync(faviconPath, "utf8");
  assert.match(favicon, /viewBox="0 0 64 64"/);
  assert.match(favicon, /#FFE600/);
  assert.match(favicon, /#00F5D4/);
  assert.match(favicon, /#FF3AF2/);
  assert.match(favicon, /scale\(0\.0625\)/);
  assert.doesNotMatch(favicon, /translate\(/);
});
