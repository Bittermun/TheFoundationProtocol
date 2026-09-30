#!/usr/bin/env node
/**
 * stop_py_gate.mjs
 *
 * Antigravity Stop hook for TheFoundationProtocol:
 * Checks if any Python (.py) files were modified in the working tree.
 * If so, runs a fast Ruff syntax/import/undefined-name check using
 * `.dist_verify/runtime/Scripts/python.exe` and injects a message if errors exist.
 */

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

function main() {
  const cwd = process.cwd();
  const venvPy = path.join(cwd, ".dist_verify", "runtime", "Scripts", "python.exe");

  if (!fs.existsSync(venvPy)) {
    process.exit(0);
  }

  let statusOut = "";
  try {
    statusOut = execFileSync("git", ["status", "--porcelain"], {
      cwd,
      encoding: "utf8",
      timeout: 5000,
    });
  } catch {
    process.exit(0);
  }

  const modifiedPyFiles = statusOut
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 3 && !line.startsWith("D "))
    .map((line) => {
      const raw = line.slice(2).trim();
      const arrowIdx = raw.indexOf(" -> ");
      return (arrowIdx !== -1 ? raw.slice(arrowIdx + 4) : raw).replace(/^"|"$/g, "");
    })
    .filter((f) => f.endsWith(".py") && fs.existsSync(path.join(cwd, f)));

  if (modifiedPyFiles.length === 0) {
    process.exit(0);
  }

  try {
    execFileSync(
      venvPy,
      [
        "-m",
        "ruff",
        "check",
        "--select",
        "E4,E7,E9,F",
        "--ignore",
        "E731",
        ...modifiedPyFiles,
      ],
      { cwd, encoding: "utf8", timeout: 15000, stdio: "pipe" }
    );
    process.exit(0);
  } catch (err) {
    const out = ((err.stdout || "") + "\n" + (err.stderr || "")).trim();
    const snippet = out.split(/\r?\n/).slice(0, 20).join("\n");
    process.stdout.write(
      JSON.stringify({
        message: `[TFP Stop Gate] Ruff detected issues in modified Python files:\n${snippet}`,
      })
    );
    process.exit(0);
  }
}

main();
