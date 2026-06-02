import { spawn } from "node:child_process";
import { config } from "../config.js";

export async function runPandoc(args: string[], cwd: string) {
  return new Promise<void>((resolve, reject) => {
    const child = spawn(config.pandocPath, args, {
      cwd,
      stdio: ["ignore", "pipe", "pipe"]
    });

    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error(`Pandoc timed out after ${config.pandocTimeoutSeconds}s`));
    }, config.pandocTimeoutSeconds * 1000);

    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });

    child.on("close", (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(stderr.trim() || `Pandoc failed with code ${code}`));
      }
    });
  });
}

