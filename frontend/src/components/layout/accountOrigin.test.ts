import { describe, expect, it } from "vitest";

import { messages, type MessageKey } from "@/app/messages";
import { accountOrigin } from "./accountOrigin";

const zh = (key: MessageKey) => messages["zh-CN"][key];

describe("账号菜单里的账号来源", () => {
  it("连本机、用户名加密码:本地账号", () => {
    expect(accountOrigin(zh, null, [])).toBe("本地账号");
  });

  it("连团队服务器:说出是哪一台,不再说本地", () => {
    expect(accountOrigin(zh, "team.example.com:8800", [])).toBe("team.example.com:8800 上的账号");
  });

  it("第三方登录:说出是哪家,和服务器那一半并列", () => {
    expect(accountOrigin(zh, null, ["google"])).toBe("本地账号 · 通过 Google 登录");
    expect(accountOrigin(zh, "team.example.com", ["apple", "google"])).toBe("team.example.com 上的账号 · 通过 Apple / Google 登录");
  });

  it("认不出的登录方原样露出 id,而不是显示成空", () => {
    expect(accountOrigin(zh, null, ["github"])).toBe("本地账号 · 通过 github 登录");
  });
});
