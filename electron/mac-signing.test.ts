import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import vm from "node:vm";
import { afterAll, describe, expect, it, vi } from "vitest";
const { needsCodeSignature, isTransientSigningFailure } =
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

describe("签名重试", () => {
  // 上面那两条只证明「认得出这几句话」。这一条证明**循环真的会重来** ——
  // 谓词写对了但循环写错(条件反了、或者 throw 排在重试之前),症状同样是构建红掉。
  //
  // 用 require.cache 塞一个假的 @electron/osx-sign:sign-mac.cjs 是在函数体里 require 它的,
  // 所以注入来得及。vi.doMock 在这里没用 —— createRequire 走的是 CommonJS 解析,绕开了 vitest。
  const require_ = createRequire(import.meta.url);
  function withFakeSigner<T>(signAsync: () => Promise<unknown>, run: (signMac: never) => T): T {
    const id = require_.resolve("@electron/osx-sign");
    const saved = require_.cache[id];
    require_.cache[id] = { id, filename: id, loaded: true, exports: { signAsync } } as never;
    delete require_.cache[require_.resolve("../scripts/sign-mac.cjs")];
    try {
      return run(require_("../scripts/sign-mac.cjs"));
    } finally {
      if (saved) require_.cache[id] = saved;
      else delete require_.cache[id];
      delete require_.cache[require_.resolve("../scripts/sign-mac.cjs")];
    }
  }

  it("撞上会自己好的失败时重来,并最终返回成功的结果", async () => {
    let calls = 0;
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      await withFakeSigner(
        async () => {
          calls += 1;
          if (calls === 1) throw new Error('/x/a.so: internal error in Code Signing subsystem');
          return "signed";
        },
        async (signMac: never) => {
          vi.useFakeTimers();
          const pending = (signMac as unknown as (o: unknown) => Promise<string>)({ app: "/x/A.app" });
          await vi.advanceTimersByTimeAsync(5000);
          await expect(pending).resolves.toBe("signed");
          vi.useRealTimers();
        },
      );
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
    await withFakeSigner(
      async () => { calls += 1; throw new Error("no identity found"); },
      async (signMac: never) => {
        await expect(
          (signMac as unknown as (o: unknown) => Promise<string>)({ app: "/x/A.app" }),
        ).rejects.toThrow("no identity found");
      },
    );
    expect(calls).toBe(1);
  });
});
