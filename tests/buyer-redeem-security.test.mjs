import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const buyerPath = resolve("frontend/src/views/BuyerRedeem.vue");
const adminPath = resolve("frontend/src/views/AdminApp.vue");
const helperPath = resolve("frontend/src/utils/turnstile.ts");

test("buyer loads progressive redeem security settings", () => {
  const source = readFileSync(buyerPath, "utf8");

  assert.match(source, /\/api\/public\/redeem-settings/);
  assert.match(source, /challengeRequired/);
  assert.match(source, /serviceAvailable/);
  assert.match(source, /turnstile_token:\s*turnstileToken\.value/);
  assert.match(source, /loadRedeemSettings/);
});

test("buyer loads Cloudflare only when the challenge is required", () => {
  const source = readFileSync(buyerPath, "utf8");

  assert.match(source, /if\s*\(!challengeRequired\.value\)\s*return/);
  assert.match(source, /loadTurnstileScript/);
  assert.match(source, /id="turnstile-redeem-widget"/);
  assert.match(source, /:disabled="loading \|\| !serviceAvailable"/);
});

test("admin and buyer share one Turnstile script loader", () => {
  assert.equal(existsSync(helperPath), true, "shared Turnstile loader is missing");
  const helper = readFileSync(helperPath, "utf8");
  const admin = readFileSync(adminPath, "utf8");
  const buyer = readFileSync(buyerPath, "utf8");

  assert.match(helper, /export function loadTurnstileScript/);
  assert.match(helper, /challenges\.cloudflare\.com\/turnstile\/v0\/api\.js/);
  assert.match(admin, /from '\.\.\/utils\/turnstile'/);
  assert.match(buyer, /from '\.\.\/utils\/turnstile'/);
});

test("buyer uses a responsive Turnstile widget", () => {
  const helper = readFileSync(helperPath, "utf8");
  const buyer = readFileSync(buyerPath, "utf8");

  assert.match(helper, /size\?:\s*'normal'\s*\|\s*'compact'\s*\|\s*'flexible'/);
  assert.match(buyer, /size:\s*'flexible'/);
});

test("admin and buyer bind Turnstile tokens to distinct actions", () => {
  const helper = readFileSync(helperPath, "utf8");
  const admin = readFileSync(adminPath, "utf8");
  const buyer = readFileSync(buyerPath, "utf8");

  assert.match(helper, /action\?:\s*string/);
  assert.match(admin, /action:\s*'admin_login'/);
  assert.match(buyer, /action:\s*'buyer_redeem'/);
});

test("a failed Turnstile script load can be retried", () => {
  const helper = readFileSync(helperPath, "utf8");

  assert.match(
    helper,
    /script\.onerror\s*=\s*\(\)\s*=>\s*\{[^}]*script\.remove\(\)[^}]*reject/s,
    "failed script elements must be removed before the loading promise is cleared",
  );
});
