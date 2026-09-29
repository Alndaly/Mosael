import fs from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";

import { afterEach, describe, expect, it } from "vitest";

// CommonJS is intentional: Electron main loads this exact module.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { resolveMasterKey, generateFernetKey, shellToken, PLAIN_NAME, SEALED_NAME } = require("./master-key.cjs") as {
  resolveMasterKey: (dataDir: string, safeStorage: FakeSafeStorage) => { key: string; sealed: boolean };
  shellToken: (key: string) => string;
  generateFernetKey: () => string;
  PLAIN_NAME: string;
  SEALED_NAME: string;
};

type FakeSafeStorage = {
  isEncryptionAvailable(): boolean;
  encryptString(value: string): Buffer;
  decryptString(value: Buffer): string;
};

/** 钥匙串的替身:封存就是加一个前缀再反转,解不开别的东西。 */
function keychain(available = true): FakeSafeStorage {
  return {
    isEncryptionAvailable: () => available,
    encryptString: (value) => Buffer.from(`sealed:${[...value].reverse().join("")}`),
    decryptString: (value) => {
      const text = value.toString();
      if (!text.startsWith("sealed:")) throw new Error("not sealed by this keychain");
      return [...text.slice("sealed:".length)].reverse().join("");
    },
  };
}

const roots: string[] = [];
function dataDir(): string {
  const root = fs.mkdtempSync(path.join(tmpdir(), "mosael-key-"));
  roots.push(root);
  return root;
}
afterEach(() => {
  for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true });
});

describe("主密钥由系统钥匙串保管", () => {
  it("新装:生成一把 Fernet 形状的密钥,只以封存的形态落盘", () => {
    const dir = dataDir();
    const { key, sealed } = resolveMasterKey(dir, keychain());
    expect(sealed).toBe(true);
    expect(key).toMatch(/^[A-Za-z0-9_-]{43}=$/);
    expect(fs.existsSync(path.join(dir, PLAIN_NAME))).toBe(false);
    expect(fs.readFileSync(path.join(dir, SEALED_NAME)).toString()).not.toContain(key);
    expect(resolveMasterKey(dir, keychain()).key, "下次启动取回的是同一把").toBe(key);
  });

  it("老版本留下的明文 secret.key:封存同一把,然后删掉明文 —— 已存的凭据照样解得开", () => {
    const dir = dataDir();
    const old = generateFernetKey();
    fs.writeFileSync(path.join(dir, PLAIN_NAME), `${old}\n`);
    expect(resolveMasterKey(dir, keychain())).toEqual({ key: old, sealed: true });
    expect(fs.existsSync(path.join(dir, PLAIN_NAME))).toBe(false);
    expect(resolveMasterKey(dir, keychain()).key).toBe(old);
  });

  it("封存之后又冒出一份不一样的明文:以封存的为准,不替人删它", () => {
    const dir = dataDir();
    const { key } = resolveMasterKey(dir, keychain());
    fs.writeFileSync(path.join(dir, PLAIN_NAME), "someone-elses-key");
    expect(resolveMasterKey(dir, keychain()).key).toBe(key);
    expect(fs.existsSync(path.join(dir, PLAIN_NAME))).toBe(true);
  });

  it("没有可用的钥匙串:不封存,后端照旧用数据目录里的文件;没有就先建好,两边拿同一把", () => {
    const dir = dataDir();
    fs.writeFileSync(path.join(dir, PLAIN_NAME), "plain");
    expect(resolveMasterKey(dir, keychain(false))).toEqual({ key: "plain", sealed: false });
    expect(fs.readFileSync(path.join(dir, PLAIN_NAME), "utf8")).toBe("plain");
    expect(fs.existsSync(path.join(dir, SEALED_NAME))).toBe(false);
    const fresh = dataDir();
    const made = resolveMasterKey(fresh, keychain(false));
    expect(made.sealed).toBe(false);
    expect(fs.readFileSync(path.join(fresh, PLAIN_NAME), "utf8")).toBe(made.key);
  });

  it("壳令牌和后端(core/shell_origin)同一个算法:同一把钥匙算出同一个数", () => {
    expect(shellToken("test-master-key")).toBe("0a309c0628230652b8d072869e0206b5895ccbe6683c9a1e5ea9908583c9a6fb");
  });
});
