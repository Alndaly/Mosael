import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import vm from "node:vm";
import { afterAll, describe, expect, it, vi } from "vitest";
const { needsCodeSignature, isTransientSigningFailure, signWith } =
  createRequire(import.meta.url)("../scripts/sign-mac.cjs");
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-signing-test-"));
afterAll(() => fs.rmSync(temporary, { recursive: true, force: true }));
function file(name: string, content: Buffer) {
  const target = path.join(temporary, name);
  fs.writeFileSync(target, content);
  return target;
}
describe("macOS signing scope", () => {
  it("signs native executables regardless of filename, including universal binaries", () => {
    for (const magic of ["cffaedfe", "feedface", "cafebabe", "bfbafeca"]) {
      expect(needsCodeSignature(file(`${magic}.dat`, Buffer.from(magic + "00000000", "hex")))).toBe(true);
    }
    expect(needsCodeSignature(temporary)).toBe(true);
  });
  it("leaves non-native resources inside the bundle's resource seal", () => {
    for (const [name, content] of [
      ["codec.wasm", "0061736d01000000"],
      ["font.ttf", "00010000000a0000"],
      ["python.pyc", "a70d0d0a00000000"],
      ["windows.exe", "4d5a900003000000"],
      ["empty", ""],
    ]) expect(needsCodeSignature(file(name, Buffer.from(content, "hex")))).toBe(false);
  });
  it("does not silently skip files that cannot be inspected", () => {
    expect(() => needsCodeSignature(path.join(temporary, "missing"))).toThrow();
  });
});

describe("release signing keychain", () => {
  it("unlocks the temporary keychain with its own password when importing separately encrypted certificates", async () => {
    const rootRequire = createRequire(import.meta.url);
    const builderRequire = createRequire(rootRequire.resolve("electron-builder"));
    const sourcePath = builderRequire.resolve("app-builder-lib/out/codeSign/macCodeSign.js");
    const dependencyRequire = createRequire(sourcePath);
    const commands: string[][] = [];
    const context = {
      exports: {} as { createKeychain: (options: object) => Promise<unknown> },
      __dirname: path.dirname(sourcePath),
      process: { env: { TRAVIS: "true" } },
      require: (name: string) => {
        if (name === "builder-util") return {
          ...dependencyRequire(name),
          exec: async (_executable: string, args: string[]) => { commands.push(args); return ""; },
        };
        if (name === "./codesign") return { importCertificate: async (link: string) => link };
        return dependencyRequire(name);
      },
    };
    vm.runInNewContext(fs.readFileSync(sourcePath, "utf8"), context);
    await context.exports.createKeychain({
      tmpDir: {}, currentDir: temporary,
      cscLink: "/mock/application.p12", cscKeyPassword: "application-certificate-password",
      cscILink: "/mock/installer.p12", cscIKeyPassword: "installer-certificate-password",
    });
    const keychainPassword = commands.find(args => args[0] === "create-keychain")![2];
    expect(keychainPassword).toBeTruthy();
    const imports = commands.filter(args => args[0] === "import");
    expect(imports.map(args => args[args.indexOf("-P") + 1])).toEqual([
      "application-certificate-password", "installer-certificate-password",
    ]);
    const partitions = commands.filter(args => args[0] === "set-key-partition-list");
    expect(partitions).toHaveLength(2);
    expect(partitions.map(args => args[args.indexOf("-k") + 1])).toEqual([
      keychainPassword, keychainPassword,
    ]);
  });
});

describe("会自己好的签名失败", () => {
  // 三条都是真实构建里抓到的原话。前两条是同一件事的两层措辞:codesign 自己说
  // 「internal error」,electron-builder 转出来是「Operation not permitted」——
  // 只认其中一条的话,真实构建里看到的那一条恰好漏掉。
  it("认得出包刚铺完时签名太早的那两种说法", () => {
    expect(isTransientSigningFailure(
      new Error("/x/Mosael.app/Contents/Resources/_rust.abi3.so: internal error in Code Signing subsystem"),
    )).toBe(true);
    expect(isTransientSigningFailure(
      new Error("Command failed: codesign --sign …\n/x/_rust.abi3.so: Operation not permitted"),
    )).toBe(true);
    expect(isTransientSigningFailure(new Error("The timestamp service is not available"))).toBe(true);
  });

  it("其余失败立刻抛,不浪费两轮退避", () => {
    expect(isTransientSigningFailure(new Error("no identity found"))).toBe(false);
    expect(isTransientSigningFailure(new Error("resource fork, Finder information, or similar detritus not allowed"))).toBe(false);
    expect(isTransientSigningFailure(new Error("invalid or unsupported format for signature"))).toBe(false);
  });
});

describe("签名钩子接的是装着的那一版 osx-sign", () => {
  // 1.x 的入口叫 signAsync、CommonJS;2.x 改名 sign、只发 ESM。钩子取错名字的话,
  // 只有云端带证书的那次打包才会炸 —— 在这里先炸。
  it("它导出 sign", async () => {
    const osxSign = await import("@electron/osx-sign");
    expect(typeof osxSign.sign).toBe("function");
  });
});

describe("签名重试", () => {
  // 上面那两条只证明「认得出这几句话」。这一条证明**循环真的会重来** ——
  // 谓词写对了但循环写错(条件反了、或者 throw 排在重试之前),症状同样是构建红掉。
  // 循环和真正的签名函数分开(signWith),所以这里直接喂一个假的,不用去动模块缓存。
  it("撞上会自己好的失败时重来,并最终返回成功的结果", async () => {
    let calls = 0;
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      vi.useFakeTimers();
      const pending = signWith(async () => {
        calls += 1;
        if (calls === 1) throw new Error('/x/a.so: internal error in Code Signing subsystem');
        return "signed";
      }, { app: "/x/A.app" });
      await vi.advanceTimersByTimeAsync(5000);
      await expect(pending).resolves.toBe("signed");
      vi.useRealTimers();
      expect(calls).toBe(2);
      // 重试必须留下痕迹,否则下次没人知道这次构建撞过。
      expect(warn).toHaveBeenCalledWith(expect.stringContaining("第 1 次签名失败"));
    } finally {
      vi.useRealTimers();
      warn.mockRestore();
    }
  });

  it("不会为认不出的失败白等两轮退避", async () => {
    let calls = 0;
    await expect(
      signWith(async () => { calls += 1; throw new Error("no identity found"); }, { app: "/x/A.app" }),
    ).rejects.toThrow("no identity found");
    expect(calls).toBe(1);
  });
});
