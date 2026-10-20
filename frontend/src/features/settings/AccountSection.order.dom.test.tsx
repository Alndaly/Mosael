/** @vitest-environment jsdom */
/**
 * 设置 → 账户的**块顺序**、**页头**与**方位指代**。
 *
 * 维护者看完成品说:「密码不应该放在下面吧,容易引起误解」。误会的来由是顺序:
 * 此前密码被别的块隔开,看着像那块的密码;而密码属于本地账号,放在它后面归属才一眼就清。
 *
 * 现在的顺序:**本地账号**(头像、用户名、昵称、签名)→ **登录密码**(紧跟本地账号)。
 * 页头只描述这一页有的东西 —— 本地账号(这台机器上的身份)。
 *
 * 这一页不再用「上面 / 下面 / 如上」指位置 —— 谁在上面是会随排版和窗口变化的,而名字不会。
 */
import React from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { messages } from "@/app/messages";

vi.mock("@/app/auth", () => ({
  useAuth: () => ({
    user: { id: "user-1", username: "demo", display_name: "Demo", signature: "", avatar_key: null },
    updateProfile: vi.fn(),
    changePassword: vi.fn(),
    updateAvatar: vi.fn(),
    logout: vi.fn(),
  }),
}));
vi.mock("@/app/preferences", async () => {
  const { messages: table } = await import("@/app/messages");
  return {
    useI18n: () => (key: keyof (typeof table)["zh-CN"]) => table["zh-CN"][key],
    usePreferences: () => ({ locale: "zh-CN", preferences: {}, updatePreferences: vi.fn() }),
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { AccountSection } from "./AccountSection";

afterEach(cleanup);

/** `a` 在文档里排在 `b` 前面。 */
function before(a: Element, b: Element): boolean {
  return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe("账户页的块顺序", () => {
  it("本地账号在最上 → 登录密码紧跟本地账号", async () => {
    render(<AccountSection />);

    const local = screen.getByText("本地账号", { selector: "strong" });
    const username = screen.getByText("用户名");
    const password = screen.getByText("登录密码", { selector: "strong" });

    //: 本地账号是第一块。
    const firstBlock = document.querySelector('[data-slot="settings-group-content"] > [data-slot="settings-block"]');
    expect(firstBlock?.contains(local), "本地账号应是第一块").toBe(true);

    expect(before(local, username), "本地账号的资料应在本地账号标题之后").toBe(true);
    expect(before(username, password), "登录密码应在本地账号资料之后").toBe(true);
    //: 密码紧跟本地账号:中间不再夹着别的账号块。
    expect(before(local, password), "登录密码应在本地账号之后").toBe(true);
    //: 渲染出来的整页文字里也不许再有方位指代。
    expect(document.body.textContent ?? "").not.toMatch(/上面|下面|如上|上述/);
  });
});

describe("账户页的页头", () => {
  it("只描述这一页真正有的东西:本地账号", async () => {
    render(<AccountSection />);

    const description = document.querySelector('[data-slot="settings-group-description"]');
    const text = description?.textContent ?? "";
    expect(text, "页头要说是哪个账号").toContain("本地账号");
    expect(text, "这一页已经没有 MosaelCloud 账号块了,页头不该再提它").not.toContain("MosaelCloud");
  });
});

/** 这一页真正渲染到的文案键。 */
const ACCOUNT_KEYS = [
  "settingsAccount",
  "railLocalAccount",
  "railServerAccount",
  "railSignedInWith",
  "signOut",
  "avatarChange",
  "avatarUpdated",
  "avatarUpdateFailed",
  "profileSaving",
  "profileSaved",
  "profileSaveFailed",
  "settingsUsername",
  "settingsUsernameDesc",
  "usernameChange",
  "usernameChangeConfirm",
  "usernameChanged",
  "teamUsernameShort",
  "displayName",
  "displayNameDesc",
  "signature",
  "signatureDesc",
  "signaturePlaceholder",
  "settingsPassword",
  "settingsPasswordDesc",
  "currentPassword",
  "newPassword",
  "confirmPassword",
  "updatePassword",
  "passwordMismatch",
  "passwordTooShort",
  "passwordUpdated",
  "passwordUpdateFailed",
] as const satisfies readonly (keyof (typeof messages)["zh-CN"])[];

describe("账户页的方位指代", () => {
  it("组件里不再用「上面 / 下面 / 如上」指位置(注释也算)", () => {
    const source = readFileSync(join(import.meta.dirname, "AccountSection.tsx"), "utf8");
    expect(source).not.toMatch(/上面|下面|如上|上述/);
  });

  it("这一页的文案不含方位指代(中英两份)", () => {
    const zh = messages["zh-CN"] as Record<string, string>;
    const en = messages["en-US"] as Record<string, string>;
    const offenders: string[] = [];
    for (const key of ACCOUNT_KEYS) {
      if (/上面|下面|如上|上述/.test(zh[key])) offenders.push(`zh-CN/${key}: ${zh[key]}`);
      if (/\b(above|below)\b/i.test(en[key])) offenders.push(`en-US/${key}: ${en[key]}`);
    }
    expect(offenders).toEqual([]);
  });
});
