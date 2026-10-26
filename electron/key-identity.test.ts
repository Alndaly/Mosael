import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { keychainName, rememberKeychainName } from "./key-identity.cjs";

const dirs: string[] = [];
const dataDir = () => {
  const dir = mkdtempSync(join(tmpdir(), "mosael-key-identity-"));
  dirs.push(dir);
  return dir;
};

afterEach(() => {
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

describe("数据目录的主密钥归属", () => {
  it("默认生产目录用 Mosael,新的开发目录用 Mosael Dev", () => {
    expect(keychainName(dataDir())).toBe("Mosael");
    expect(keychainName(dataDir(), { dev: true })).toBe("Mosael Dev");
  });

  it("旧版没有 owner 文件但有封存钥匙:按打包版 Mosael 推断", () => {
    const dir = dataDir();
    writeFileSync(join(dir, "secret.key.sealed"), "sealed");
    expect(keychainName(dir, { dev: true })).toBe("Mosael");
  });

  it("owner 文件优先,并由 remember 写成 0600", () => {
    const dir = dataDir();
    writeFileSync(join(dir, "secret.key.sealed"), "sealed");
    rememberKeychainName(dir, "Mosael Dev");
    expect(keychainName(dir)).toBe("Mosael Dev");
    expect(readFileSync(join(dir, "secret.key.owner"), "utf8")).toBe("Mosael Dev\n");
  });
});
