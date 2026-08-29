import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { extname, resolve } from "node:path";

const ignoredBinaryExtensions = new Set([
  ".gif",
  ".ico",
  ".jpeg",
  ".jpg",
  ".png",
  ".tar",
  ".gz",
  ".zip",
]);

function trackedFiles() {
  return execFileSync("git", ["ls-files", "--cached", "--others", "--exclude-standard"], { encoding: "utf8" })
    .split(/\r?\n/)
    .map((file) => file.trim())
    .filter((file) => file && existsSync(resolve(file)));
}

function trackedText() {
  return trackedFiles()
    .filter((file) => !ignoredBinaryExtensions.has(extname(file).toLowerCase()))
    .map((file) => readFileSync(resolve(file), "utf8"))
    .join("\n");
}

const awsAccessKeyPattern = new RegExp(
  `(?:^|[^A-Za-z0-9])${["AK", "IA"].join("")}[0-9A-Z]{16}(?:$|[^A-Za-z0-9])`,
);

test("tracked paths exclude runtime data, local config, and release archives", () => {
  const files = trackedFiles();

  assert.equal(files.some((file) => file.startsWith("data/")), false);
  assert.equal(files.some((file) => file.startsWith(".claude/")), false);
  assert.equal(files.some((file) => file.startsWith(".worktrees/")), false);
  assert.equal(files.some((file) => file.endsWith(".tar.gz")), false);
  assert.equal(
    files.some((file) => file.endsWith(".env") || (file.includes(".env.") && !file.endsWith(".env.example"))),
    false,
  );
});

test("tracked text contains no deployment identity or credential markers", () => {
  const content = trackedText();
  const forbidden = [
    ["lucky", "sy", "me"].join("."),
    ["lucky", "sus", "github", "io"].join("."),
    ["链动", "小铺"].join(""),
    ["45", "205", "25", "173"].join("."),
    ["47", "93", "203", "36"].join("."),
    ["39", "106", "224", "139"].join("."),
    ["107", "170", "156", "227"].join("."),
    ["-----", "BEGIN"].join(""),
    ["s", "k-"].join(""),
    ["g", "hp_"].join(""),
    ["F", ":/"].join(""),
    ["C", ":/"].join(""),
    ["D", ":/"].join(""),
    ["/www", "/wwwroot"].join(""),
  ];

  for (const marker of forbidden) {
    assert.equal(content.includes(marker), false, `found forbidden marker: ${marker}`);
  }
  assert.equal(awsAccessKeyPattern.test(content), false, "found an AWS access key-shaped value");
});
