import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const candidates = process.platform === "win32"
  ? [join(".venv", "Scripts", "python.exe"), "python", "py"]
  : [join(".venv", "bin", "python"), "python3", "python"];

let last;
for (const command of candidates) {
  if ((command.includes("/") || command.includes("\\")) && !existsSync(command)) continue;
  const args = command === "py"
    ? ["-3", "-m", "unittest", "discover", "-s", "tests", "-v"]
    : ["-m", "unittest", "discover", "-s", "tests", "-v"];
  const result = spawnSync(command, args, { stdio: "inherit", shell: false });
  last = result;
  if (!result.error) process.exit(result.status ?? 1);
}

console.error(last?.error?.message || "No Python executable found");
process.exit(1);
