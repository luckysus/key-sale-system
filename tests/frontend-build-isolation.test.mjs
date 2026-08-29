import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

function javascriptIn(directory) {
  if (!existsSync(directory)) return "";
  return readdirSync(directory, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".js"))
    .map((entry) => readFileSync(join(entry.parentPath, entry.name), "utf8"))
    .join("\n");
}

function cssIn(directory) {
  if (!existsSync(directory)) return "";
  return readdirSync(directory, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".css"))
    .map((entry) => readFileSync(join(entry.parentPath, entry.name), "utf8"))
    .join("\n");
}

test("production defines separate buyer and admin entries", () => {
  const required = [
    "frontend/admin.html",
    "frontend/buyer.html",
    "frontend/src/admin-main.ts",
    "frontend/src/buyer-main.ts",
  ];
  for (const path of required) assert.equal(existsSync(resolve(path)), true, `${path} is missing`);

  const config = readFileSync(resolve("frontend/vite.config.ts"), "utf8");
  const pkg = JSON.parse(readFileSync(resolve("package.json"), "utf8"));
  assert.match(config, /mode === 'buyer'/);
  assert.match(config, /command === 'serve'/);
  assert.match(config, /dist\/\$\{target\}/);
  assert.match(config, /\$\{target\}-static/);
  assert.match(pkg.scripts["build:admin"], /--mode admin/);
  assert.match(pkg.scripts["build:buyer"], /--mode buyer/);
});

test("backend serves and isolates host-specific static assets", () => {
  const source = readFileSync(resolve("backend/main.py"), "utf8");
  assert.match(source, /\/admin-static/);
  assert.match(source, /\/buyer-static/);
  assert.match(source, /admin\.html/);
  assert.match(source, /buyer\.html/);
  assert.match(source, /host in BUYER_HOSTS.*admin-static/s);
  assert.match(source, /host in ADMIN_HOSTS.*buyer-static/s);
});

test("built buyer bundle excludes management implementation", () => {
  const buyerDir = resolve("frontend/dist/buyer");
  const adminDir = resolve("frontend/dist/admin");
  assert.equal(existsSync(buyerDir), true, "buyer build is missing; run npm run build");
  assert.equal(existsSync(adminDir), true, "admin build is missing; run npm run build");

  const buyerBundle = javascriptIn(buyerDir);
  const adminBundle = javascriptIn(adminDir);
  assert.doesNotMatch(buyerBundle, /\/api\/admin\//);
  assert.doesNotMatch(buyerBundle, /api_key|bearer_token/);
  assert.match(adminBundle, /\/api\/admin\//);
});

test("buyer entry and built CSS exclude management styles", () => {
  const entry = readFileSync(resolve("frontend/src/buyer-main.ts"), "utf8");
  const buyerCss = cssIn(resolve("frontend/dist/buyer"));

  assert.match(entry, /\.\/styles\/buyer\.css/);
  assert.doesNotMatch(entry, /\.\/styles\/app\.css/);
  assert.doesNotMatch(buyerCss, /\.admin-shell/);
});

test("buyer JavaScript stays below the public bundle budget", () => {
  const assets = resolve("frontend/dist/buyer/assets");
  const bytes = readdirSync(assets)
    .filter((name) => name.endsWith(".js"))
    .reduce((total, name) => total + statSync(join(assets, name)).size, 0);

  assert.ok(bytes < 600_000, `buyer JavaScript is ${(bytes / 1024).toFixed(1)} KiB`);
});
