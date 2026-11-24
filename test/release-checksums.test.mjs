import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SCRIPT = path.join(ROOT, "scripts", "write-release-checksums.mjs");

const PUBLISHED = [
  "Mosael-2.6.15-arm64.dmg",
  "Mosael-2.6.15-mac-signed.zip",
  "Mosael-2.6.15-mac-signed.zip.blockmap",
  "Mosael-Setup-2.6.15.exe",
  "Mosael-Setup-2.6.15.exe.blockmap",
  "dev.mosael.blender.zip",
  "latest-mac.yml",
  "latest.yml",
  "registry.json",
];
const NOT_PUBLISHED = ["builder-debug.yml", "builder-effective-config.yaml", "index.html"];

test("SHA256SUMS 覆盖用户会下载的全部附件,含差分更新的 .blockmap", () => {
  const release = mkdtempSync(path.join(tmpdir(), "mosael-checksums-"));
  try {
    for (const name of [...PUBLISHED, ...NOT_PUBLISHED]) writeFileSync(path.join(release, name), name);
    mkdirSync(path.join(release, "mac-arm64"));
    writeFileSync(path.join(release, "SHA256SUMS"), "stale\n");

    execFileSync(process.execPath, [SCRIPT, "--release", release], { cwd: ROOT });

    const lines = readFileSync(path.join(release, "SHA256SUMS"), "utf8").trim().split("\n");
    assert.deepEqual(
      lines.map((line) => line.split("  ")[1]),
      PUBLISHED.toSorted(),
    );
    for (const line of lines) {
      const [digest, name] = line.split("  ");
      assert.equal(digest, createHash("sha256").update(name).digest("hex"), name);
    }
  } finally {
    rmSync(release, { recursive: true, force: true });
  }
});
