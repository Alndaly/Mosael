import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import vm from "node:vm";
import { describe, expect, it, vi } from "vitest";

const ROOT = path.resolve(__dirname, "..");
const SOURCE = fs.readFileSync(path.join(ROOT, "electron/webauthn.cjs"), "utf8");
const ENTITLEMENTS = fs.readFileSync(path.join(ROOT, "build/entitlements.mac.plist"), "utf8");
const PACKAGE = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
const { readWebAuthnKeychainGroup } = createRequire(import.meta.url)("./mac-signature.cjs");
const team = "27W3D2ZUT9";
const appId = PACKAGE.build.appId;
const group = `${team}.${appId}.webauthn`;
const validEntitlements = {
  "com.apple.application-identifier": `${team}.${appId}`,
  "com.apple.developer.team-identifier": team,
  "keychain-access-groups": [group],
};

function signatureReader(entitlements: object = validEntitlements, metadata = `TeamIdentifier=${team}\n`) {
  return vi.fn()
    .mockReturnValueOnce({ status: 0 })
    .mockReturnValueOnce({ status: 0, stdout: "signed plist", stderr: metadata })
    .mockReturnValueOnce({ status: 0, stdout: JSON.stringify(entitlements) });
}

function loadWebAuthn(platform = "darwin", isPackaged = true, signedGroup = group) {
  const app = { isPackaged, configureWebAuthn: vi.fn() };
  const readGroup = vi.fn(() => signedGroup);
  const target = { on: vi.fn() };
  const dialog = { showMessageBoxSync: vi.fn() };
  const context = {
    module: { exports: {} as Record<string, (...args: any[]) => any> },
    process: { platform, execPath: "/Applications/Mosael.app/Contents/MacOS/Mosael", env: {} },
    require: (name: string) => name === "electron"
      ? { app, dialog, session: { fromPartition: () => target } }
      : { readWebAuthnKeychainGroup: readGroup },
  };
  vm.runInNewContext(SOURCE, context);
  return { ...context.module.exports, app, readGroup, target, dialog };
}

describe("installed macOS signature", () => {
  it("uses the verified executable's team and keychain entitlement without environment variables", () => {
    const run = signatureReader();
    expect(readWebAuthnKeychainGroup("/Applications/Mosael.app/Contents/MacOS/Mosael", appId, run)).toBe(group);
    expect(run.mock.calls[0][1]).toContain("--verify");
    expect(run.mock.calls[2][2].input).toBe("signed plist");
  });
  it.each([
    [{ ...validEntitlements, "keychain-access-groups": ["$(AppIdentifierPrefix)dev.mosael.app.webauthn"] }, `TeamIdentifier=${team}`],
    [{ ...validEntitlements, "com.apple.developer.team-identifier": "WRONGTEAM1" }, `TeamIdentifier=${team}`],
    [{ ...validEntitlements, "com.apple.application-identifier": `${team}.another.app` }, `TeamIdentifier=${team}`],
    [validEntitlements, "TeamIdentifier=not set"],
    [{}, `TeamIdentifier=${team}`],
  ])("rejects mismatched or missing signature prerequisites", (entitlements, metadata) => {
    expect(readWebAuthnKeychainGroup("/app", appId, signatureReader(entitlements, metadata))).toBe("");
  });
  it("rejects invalid signatures before reading their entitlements", () => {
    const run = vi.fn(() => ({ status: 1 }));
    expect(readWebAuthnKeychainGroup("/app", appId, run)).toBe("");
    expect(run).toHaveBeenCalledTimes(1);
  });
  it("fails closed on timeout or malformed plist without breaking application startup", () => {
    expect(readWebAuthnKeychainGroup("/app", appId, () => { throw new Error("timeout"); })).toBe("");
    const run = signatureReader();
    run.mockReset().mockReturnValueOnce({ status: 0 })
      .mockReturnValueOnce({ status: 0, stderr: `TeamIdentifier=${team}`, stdout: "xml" })
      .mockReturnValueOnce({ status: 0, stdout: "not json" });
    expect(readWebAuthnKeychainGroup("/app", appId, run)).toBe("");
  });
  it("ships concrete main-app entitlements and keeps restricted groups out of helpers", () => {
    expect(ENTITLEMENTS).toContain(group);
    expect(ENTITLEMENTS).not.toContain("$(AppIdentifierPrefix)");
    expect(PACKAGE.build.mac.forceCodeSigning).toBe(true);
    expect(PACKAGE.build.mac.identity).toContain(team);
    expect(PACKAGE.build.mac.provisioningProfile).toBe("build/mosael.provisionprofile");
    const inherited = fs.readFileSync(path.join(ROOT, PACKAGE.build.mac.entitlementsInherit), "utf8");
    expect(inherited).not.toContain("keychain-access-groups");
    expect(inherited).toContain("com.apple.security.cs.allow-jit");
  });
});

describe("platform authenticator wiring", () => {
  it("configures the authenticator in a signed installation", () => {
    const api = loadWebAuthn();
    expect(api.configurePlatformAuthenticator()).toBe(true);
    expect(api.readGroup).toHaveBeenCalledWith("/Applications/Mosael.app/Contents/MacOS/Mosael", appId);
    expect(api.app.configureWebAuthn).toHaveBeenCalledWith({ touchID: {
      keychainAccessGroup: group, promptReason: "verify your identity on $1",
    } });
  });
  it.each([["darwin", false], ["win32", true], ["linux", true]])("leaves unsupported builds alone", (platform, packaged) => {
    const api = loadWebAuthn(platform as string, packaged as boolean);
    expect(api.configurePlatformAuthenticator()).toBe(false);
    expect(api.readGroup).not.toHaveBeenCalled();
    expect(api.app.configureWebAuthn).not.toHaveBeenCalled();
  });
  it("does not configure an unsigned installation", () => {
    const api = loadWebAuthn("darwin", true, "");
    expect(api.configurePlatformAuthenticator()).toBe(false);
    expect(api.app.configureWebAuthn).not.toHaveBeenCalled();
  });
  it("keeps startup working if Electron cannot enable the authenticator", () => {
    const api = loadWebAuthn();
    api.app.configureWebAuthn.mockImplementation(() => { throw new Error("unavailable"); });
    expect(api.configurePlatformAuthenticator()).toBe(false);
  });
});

describe("discoverable account selection", () => {
  it("binds once and completes single, multiple and cancelled requests", () => {
    const api = loadWebAuthn();
    api.handleAccountSelection("persist:account");
    api.handleAccountSelection("persist:account");
    expect(api.target.on).toHaveBeenCalledTimes(1);
    const handler = api.target.on.mock.calls[0][1];
    const callback = vi.fn();
    const accounts = [{ name: "Alice", credentialId: "one" }, { name: "Bob", credentialId: "two" }];
    handler({}, { accounts: accounts.slice(0, 1) }, callback);
    expect(callback).toHaveBeenLastCalledWith("one");
    api.dialog.showMessageBoxSync.mockReturnValue(1);
    handler({}, { accounts, relyingPartyId: "example.com" }, callback);
    expect(callback).toHaveBeenLastCalledWith("two");
    api.dialog.showMessageBoxSync.mockReturnValue(2);
    handler({}, { accounts }, callback);
    expect(callback).toHaveBeenLastCalledWith(undefined);
    api.dialog.showMessageBoxSync.mockImplementation(() => { throw new Error("closed"); });
    handler({}, { accounts }, callback);
    expect(callback).toHaveBeenLastCalledWith(undefined);
    expect(callback).toHaveBeenCalledTimes(4);
  });
});
