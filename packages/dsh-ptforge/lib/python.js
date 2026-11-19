import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import os from "node:os";
import path from "node:path";

/** Absolute directory that holds the bundled `ptforge` Python package. */
export const ENGINE_DIR = fileURLToPath(new URL("../engine", import.meta.url));

const DEFAULT_TIMEOUTS = {
  models: 30_000,
  build: 90_000,
  inspect: 60_000,
  apply: 60_000,
  open: 90_000,
};

function pythonCandidates(config = {}) {
  const home = process.env.DSH_HOME ?? path.join(os.homedir(), ".dsh");
  const runtime = path.join(
    home,
    "dsh-runtimes",
    "dsh-primary-runtime",
    "dependencies",
    "python",
    "python.exe",
  );
  return [config.python, process.env.DSH_PTFORGE_PYTHON, process.env.DSH_PYTHON, runtime, "python", "py"].filter(
    (candidate) => typeof candidate === "string" && candidate.length > 0,
  );
}

function runOnce(python, args, options) {
  return new Promise((resolve, reject) => {
    execFile(
      python,
      ["-m", options.module ?? "ptforge", ...(options.json === false ? [] : ["--json"]), ...args],
      {
        cwd: ENGINE_DIR,
        timeout: options.timeout ?? 60_000,
        maxBuffer: 32 * 1024 * 1024,
        windowsHide: true,
        env: {
          ...process.env,
          PYTHONPATH: ENGINE_DIR,
          PYTHONIOENCODING: "utf-8",
          PYTHONUTF8: "1",
        },
      },
      (error, stdout, stderr) => {
        if (error && !(options.okCodes ?? [0]).includes(error.code)) {
          if (error.code === "ENOENT") {
            error.__missingInterpreter = true;
          } else {
            error.stderr = stderr;
            error.stdout = stdout;
          }
          reject(error);
          return;
        }
        resolve({ stdout, stderr });
      },
    );
  });
}

/** Run the bundled engine and return its parsed JSON payload. */
export async function runEngine(config, args, { timeout, module = "ptforge", json = true, okCodes = [0] } = {}) {
  const candidates = pythonCandidates(config);
  const failures = [];
  for (const python of candidates) {
    if (python.includes(path.sep) && !existsSync(python)) {
      failures.push(`${python}: not found`);
      continue;
    }
    try {
      const { stdout } = await runOnce(python, args, { timeout, module, json, okCodes });
      const text = stdout.trim();
      if (text === "") return {};
      const start = text.indexOf("{");
      return JSON.parse(start >= 0 ? text.slice(start) : text);
    } catch (error) {
      if (error.__missingInterpreter) {
        failures.push(`${python}: not found`);
        continue;
      }
      const detail = (error.stderr || "").trim().split("\n").slice(-6).join("\n");
      throw new Error(`ptforge failed (${python} ${args.join(" ")}):\n${detail || error.message}`);
    }
  }
  throw new Error(
    `no Python interpreter found for the ptforge engine. Set config.python or DSH_PTFORGE_PYTHON.\nTried: ${failures.join(", ")}`,
  );
}

export function timeoutFor(command) {
  return DEFAULT_TIMEOUTS[command] ?? 60_000;
}
