import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import vm from "node:vm";
import { afterAll, describe, expect, it } from "vitest";
const { needsCodeSignature } = createRequire(import.meta.url)("../scripts/sign-mac.cjs");
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
