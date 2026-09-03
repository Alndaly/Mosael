import fs from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";

import { unzipSync, strFromU8 } from "fflate";
import { afterEach, describe, expect, it } from "vitest";

// CommonJS is intentional: Electron main loads this exact module.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { activateStagedRestore, finalizeActivatedRestore, writeDiagnosticArchive } = require("./data-management.cjs") as {
  writeDiagnosticArchive: (destination: string, options: Record<string, unknown>) => Promise<string>;
  activateStagedRestore: (dataDir: string, stageId: string) => { previousDir: string };
  finalizeActivatedRestore: (dataDir: string) => Promise<boolean>;
};

const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true });
});

describe("data and diagnostics", () => {
  it("exports a readable diagnostic ZIP without paths or credentials", async () => {
    const root = fs.mkdtempSync(path.join(tmpdir(), "mosael-diagnostics-"));
    roots.push(root);
    const home = path.join(root, "person");
    const dataDir = path.join(home, ".mosael");
    const userDataDir = path.join(home, "Library", "Application Support", "Mosael");
    const logs = path.join(userDataDir, "logs");
    fs.mkdirSync(logs, { recursive: true });
    fs.writeFileSync(
      path.join(logs, "backend.log"),
      `render failed in ${dataDir}/media/private.mp4\nAuthorization: Bearer top-secret-token\napi_key=sk-example-secret\n{"access_token":"json-secret-value","password":"another-secret"}\n`,
    );
    fs.writeFileSync(path.join(logs, "main.log"), "renderer process exited unexpectedly\n");
    const destination = path.join(root, "diagnostics.zip");

    await writeDiagnosticArchive(destination, {
      appVersion: "1.2.3",
      platform: "darwin",
      arch: "arm64",
      homeDir: home,
      dataDir,
      userDataDir,
      secrets: ["top-secret-token"],
      logFiles: [path.join(logs, "backend.log"), path.join(logs, "main.log")],
    });

    const archive = unzipSync(fs.readFileSync(destination));
    expect(Object.keys(archive).sort()).toEqual([
      "diagnostics/backend.log",
      "diagnostics/main.log",
      "manifest.json",
    ]);
    const manifest = JSON.parse(strFromU8(archive["manifest.json"]));
    expect(manifest).toMatchObject({ format: "mosael-diagnostics", version: 1, app_version: "1.2.3" });
    const backendLog = strFromU8(archive["diagnostics/backend.log"]);
    expect(backendLog).toContain("<DATA_DIR>/media/private.mp4");
    expect(backendLog).not.toContain(home);
    expect(backendLog).not.toContain("top-secret-token");
    expect(backendLog).not.toContain("sk-example-secret");
    expect(backendLog).not.toContain("json-secret-value");
    expect(backendLog).not.toContain("another-secret");
  });

  it("atomically activates a validated restore and removes the safety copy only after health", async () => {
    const root = fs.mkdtempSync(path.join(tmpdir(), "mosael-restore-"));
    roots.push(root);
    const dataDir = path.join(root, "data");
    const stageId = "a".repeat(32);
    const stage = path.join(root, `.data.restore-${stageId}`);
    fs.mkdirSync(dataDir);
    fs.writeFileSync(path.join(dataDir, "old.txt"), "old");
    fs.mkdirSync(stage);
    fs.writeFileSync(path.join(stage, "mosael.db"), "new");
    fs.writeFileSync(
      path.join(stage, ".mosael-restore.json"),
      JSON.stringify({ format: "mosael-backup", version: 1, stage_id: stageId }),
    );

    const { previousDir } = activateStagedRestore(dataDir, stageId);

    expect(fs.readFileSync(path.join(dataDir, "mosael.db"), "utf8")).toBe("new");
    expect(fs.readFileSync(path.join(previousDir, "old.txt"), "utf8")).toBe("old");
    expect(await finalizeActivatedRestore(dataDir)).toBe(true);
    expect(fs.existsSync(previousDir)).toBe(false);
    expect(fs.existsSync(path.join(dataDir, ".mosael-restore.json"))).toBe(false);
  });
});
