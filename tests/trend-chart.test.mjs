import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import ts from "typescript";

const dashboardView = readFileSync(resolve("frontend/src/views/DashboardView.vue"), "utf8");
const dashboardStyles = readFileSync(resolve("frontend/src/styles/app.css"), "utf8");

async function loadTrendChart() {
  const path = resolve("frontend/src/utils/trendChart.ts");
  assert.ok(existsSync(path), "trend chart helper is missing");
  const source = readFileSync(path, "utf8");
  const javascript = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);
}

test("draws trend values as a smooth cubic path through every point", async () => {
  const { trendPath } = await loadTrendChart();

  assert.equal(trendPath([0, 10, 0], 100, 50, 5), "M 5 45 C 27.5 45 27.5 5 50 5 C 72.5 5 72.5 45 95 45");
});

test("keeps an all-zero smooth trend on the chart baseline", async () => {
  const { trendPath } = await loadTrendChart();

  assert.equal(trendPath([0, 0], 100, 50, 5), "M 5 45 C 50 45 50 45 95 45");
});

test("uses a shared maximum for comparable smooth trend paths", async () => {
  const { trendPath } = await loadTrendChart();

  assert.equal(trendPath([0, 5], 100, 50, 5, 10), "M 5 45 C 50 45 50 25 95 25");
});

test("dashboard renders smooth SVG paths instead of polylines", () => {
  assert.match(dashboardView, /<path\s+:d="successPath"/);
  assert.match(dashboardView, /<path\s+:d="failedPath"/);
  assert.doesNotMatch(dashboardView, /<polyline/);
});

test("recent extraction card uses the dashboard gap without extra margin", () => {
  assert.match(dashboardStyles, /\.dashboard-main\s*\+\s*\.dashboard-log-card\s*\{[^}]*margin-top:\s*0;/s);
});

test("recent extraction table uses Ant Table native fixed header", () => {
  assert.match(dashboardView, /<a-card[^>]*ref="logCardRef"[^>]*dashboard-log-card/);
  assert.match(dashboardView, /:scroll="\{ x: 900, y: logTableBodyHeight \}"/);
  assert.match(dashboardView, /new ResizeObserver\(updateLogTableBodyHeight\)/);
  assert.match(
    dashboardStyles,
    /\.dashboard-log-card \.ant-card-body\s*\{[^}]*display:\s*flex;[^}]*overflow:\s*hidden;/s,
  );
  assert.doesNotMatch(
    dashboardStyles,
    /\.dashboard-log-card \.ant-table-thead > tr > th\s*\{[^}]*position:\s*sticky/s,
    "custom sticky headers conflict with Ant Table's own scroll container",
  );
});
